import os
import sys
import datetime
import numpy as np
import cv2
import zoneinfo as zi

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QGridLayout, QComboBox,
    QFileDialog, QMessageBox, QStatusBar
)
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QCloseEvent

from capture import SeekCapture
from tracker import TrackerManager
from recorder import SessionRecorder, check_ntp_available, check_db_connection
from processing import bgr_to_qimage
from .widgets import VideoView

from config import OUTPUT_DIR as DEFAULT_OUTPUT_DIR

try:
    from tzlocal import get_localzone_name
except ImportError:
    get_localzone_name = None


def build_timezone_items(system_tz: str):
    try:
        if hasattr(zi, "available_timezones"):
            all_tz = sorted(zi.available_timezones())
        else:
            raise AttributeError
    except Exception:
        all_tz = [
            "UTC",
            "Europe/Warsaw",
            "Europe/Berlin",
            "Europe/Paris",
            "Europe/London",
            "America/New_York",
            "America/Los_Angeles",
            "Asia/Tokyo",
            "Asia/Seoul",
            "Asia/Shanghai",
        ]

    items = []
    for name in all_tz:
        parts = name.split("/")
        if len(parts) > 1:
            city = parts[-1].replace("_", " ")
        else:
            city = name
        label = f"{name} ({city})"
        if name == system_tz:
            label += ", systemowa"
        items.append((name, label))

    if system_tz and system_tz not in [tz for tz, _ in items]:
        city = system_tz.split("/")[-1].replace("_", " ")
        items.insert(0, (system_tz, f"{system_tz} ({city}, systemowa)"))

    items.sort(key=lambda x: (0 if x[0] == system_tz else 1, x[0]))
    return items


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VRTempMonit")
        self.resize(1280, 800)

        # Katalog wyjściowy
        self.output_dir = self._choose_output_dir()

        # Strefa czasowa systemu
        if get_localzone_name is not None:
            try:
                system_tz = get_localzone_name()
            except Exception:
                system_tz = "Europe/Warsaw"
        else:
            system_tz = "Europe/Warsaw"

        self.current_timezone_name = system_tz
        self.tz_items = build_timezone_items(system_tz)

        # Kamera
        self.cap = SeekCapture()
        self.cap.start()

        # Trackery / ROI
        self.trackers = [TrackerManager(), TrackerManager(), TrackerManager()]
        self.roi_rects = [None, None, None]

        # Rejestrator
        self.rec = SessionRecorder(output_dir=self.output_dir, timezone_name=self.current_timezone_name)

        self.is_measuring = False
        self.is_recording = False
        self._last_logged_seq = -1

        # UI
        root_layout = QVBoxLayout(self)
        top_layout = QHBoxLayout()
        root_layout.addLayout(top_layout)

        self.status = QStatusBar()
        root_layout.addWidget(self.status)

        # widok wideo
        self.view = VideoView(self)
        top_layout.addWidget(self.view, stretch=5)

        # panel boczny
        side = QVBoxLayout()
        top_layout.addLayout(side, stretch=2)

        # ROI / TRACKING
        grp_roi = QGroupBox("Konfiguracja ROI / Śledzenie")
        roi_grid = QGridLayout()

        self.btn_set_roi1   = QPushButton("Ustaw ROI 1")
        self.btn_start_trk1 = QPushButton("Start TRACK ROI 1")
        self.btn_stop_trk1  = QPushButton("Stop TRACK ROI 1")
        self.btn_clear_roi1 = QPushButton("Usuń ROI 1")

        self.btn_set_roi2   = QPushButton("Ustaw ROI 2")
        self.btn_start_trk2 = QPushButton("Start TRACK ROI 2")
        self.btn_stop_trk2  = QPushButton("Stop TRACK ROI 2")
        self.btn_clear_roi2 = QPushButton("Usuń ROI 2")

        self.btn_set_roi3   = QPushButton("Ustaw ROI 3")
        self.btn_start_trk3 = QPushButton("Start TRACK ROI 3")
        self.btn_stop_trk3  = QPushButton("Stop TRACK ROI 3")
        self.btn_clear_roi3 = QPushButton("Usuń ROI 3")

        roi_grid.addWidget(self.btn_set_roi1,   0, 0)
        roi_grid.addWidget(self.btn_start_trk1, 0, 1)
        roi_grid.addWidget(self.btn_stop_trk1,  0, 2)
        roi_grid.addWidget(self.btn_clear_roi1, 0, 3)

        roi_grid.addWidget(self.btn_set_roi2,   1, 0)
        roi_grid.addWidget(self.btn_start_trk2, 1, 1)
        roi_grid.addWidget(self.btn_stop_trk2,  1, 2)
        roi_grid.addWidget(self.btn_clear_roi2, 1, 3)

        roi_grid.addWidget(self.btn_set_roi3,   2, 0)
        roi_grid.addWidget(self.btn_start_trk3, 2, 1)
        roi_grid.addWidget(self.btn_stop_trk3,  2, 2)
        roi_grid.addWidget(self.btn_clear_roi3, 2, 3)

        grp_roi.setLayout(roi_grid)

        # Folder zapisu
        grp_out = QGroupBox("Folder zapisu danych")
        v_out = QVBoxLayout()
        self.lbl_output_dir = QLabel(self.output_dir)
        self.lbl_output_dir.setWordWrap(True)
        v_out.addWidget(self.lbl_output_dir)
        self.btn_change_dir = QPushButton("Zmień folder...")
        v_out.addWidget(self.btn_change_dir)
        grp_out.setLayout(v_out)

        # Strefa czasowa
        grp_tz = QGroupBox("Strefa czasowa zapisu")
        tz_layout = QVBoxLayout()
        self.lbl_tz_info = QLabel(
            "Czas sesji zapisujemy w UTC (do bazy),\n"
            "a nazwy plików i JSON w wybranej strefie."
        )
        self.combo_tz = QComboBox()
        for tz_id, label in self.tz_items:
            self.combo_tz.addItem(label, userData=tz_id)

        idx_default = 0
        for i in range(self.combo_tz.count()):
            if self.combo_tz.itemData(i) == self.current_timezone_name:
                idx_default = i
                break
        self.combo_tz.setCurrentIndex(idx_default)

        tz_layout.addWidget(self.lbl_tz_info)
        tz_layout.addWidget(self.combo_tz)
        grp_tz.setLayout(tz_layout)

        # Status sieci (NTP + DB)
        grp_net = QGroupBox("Status sieci / bazy")
        v_net = QVBoxLayout()
        self.lbl_ntp_status = QLabel("NTP: sprawdzanie...")
        self.lbl_db_status = QLabel("DB: sprawdzanie...")
        v_net.addWidget(self.lbl_ntp_status)
        v_net.addWidget(self.lbl_db_status)
        grp_net.setLayout(v_net)

        # Pomiar temperatury
        grp_meas = QGroupBox("Pomiar temperatury")
        v_meas = QVBoxLayout()
        self.btn_start_meas = QPushButton("Rozpocznij pomiar")
        self.btn_stop_meas  = QPushButton("Zakończ pomiar")
        v_meas.addWidget(self.btn_start_meas)
        v_meas.addWidget(self.btn_stop_meas)
        grp_meas.setLayout(v_meas)

        # Nagrywanie wideo
        grp_rec = QGroupBox("Nagrywanie wideo")
        v_rec = QVBoxLayout()
        self.btn_start_rec = QPushButton("Rozpocznij nagrywanie")
        self.btn_stop_rec  = QPushButton("Zakończ nagrywanie")
        self.btn_snapshot  = QPushButton("Zapisz zdjęcie")
        v_rec.addWidget(self.btn_start_rec)
        v_rec.addWidget(self.btn_stop_rec)
        v_rec.addWidget(self.btn_snapshot)
        grp_rec.setLayout(v_rec)

        # Legenda ROI
        grp_legend = QGroupBox("Legenda ROI")
        v_leg = QVBoxLayout()
        self.label_roi1 = QLabel("ROI 1 – kolor zielony")
        self.label_roi2 = QLabel("ROI 2 – kolor niebieski")
        self.label_roi3 = QLabel("ROI 3 – kolor czerwony")
        self.label_roi1.setStyleSheet("color: rgb(0,180,0); font-weight: bold;")
        self.label_roi2.setStyleSheet("color: rgb(0,0,200); font-weight: bold;")
        self.label_roi3.setStyleSheet("color: rgb(200,0,0); font-weight: bold;")
        v_leg.addWidget(self.label_roi1)
        v_leg.addWidget(self.label_roi2)
        v_leg.addWidget(self.label_roi3)
        grp_legend.setLayout(v_leg)

        # Temperatury + MEAS/REC
        self.label_temp = QLabel("ROI1: — °C | ROI2: — °C | ROI3: — °C")
        self.label_meas = QLabel("MEAS: OFF")
        self.label_rec  = QLabel("REC: OFF")

        self.btn_quit = QPushButton("ZAMKNIJ")

        side.addWidget(grp_roi)
        side.addWidget(grp_out)
        side.addWidget(grp_tz)
        side.addWidget(grp_net)
        side.addWidget(grp_meas)
        side.addWidget(grp_rec)
        side.addWidget(grp_legend)
        side.addWidget(self.label_temp)
        side.addWidget(self.label_meas)
        side.addWidget(self.label_rec)
        side.addWidget(self.btn_quit)
        side.addStretch(1)

        # Sygnały
        self.btn_set_roi1.clicked.connect(lambda: self.on_set_roi_slot(0))
        self.btn_set_roi2.clicked.connect(lambda: self.on_set_roi_slot(1))
        self.btn_set_roi3.clicked.connect(lambda: self.on_set_roi_slot(2))

        self.btn_clear_roi1.clicked.connect(lambda: self.on_clear_roi(0))
        self.btn_clear_roi2.clicked.connect(lambda: self.on_clear_roi(1))
        self.btn_clear_roi3.clicked.connect(lambda: self.on_clear_roi(2))

        self.btn_start_trk1.clicked.connect(lambda: self.on_start_track(0))
        self.btn_start_trk2.clicked.connect(lambda: self.on_start_track(1))
        self.btn_start_trk3.clicked.connect(lambda: self.on_start_track(2))

        self.btn_stop_trk1.clicked.connect(lambda: self.on_stop_track(0))
        self.btn_stop_trk2.clicked.connect(lambda: self.on_stop_track(1))
        self.btn_stop_trk3.clicked.connect(lambda: self.on_stop_track(2))

        self.btn_start_meas.clicked.connect(self.on_start_measure)
        self.btn_stop_meas.clicked.connect(self.on_stop_measure)

        self.btn_start_rec.clicked.connect(self.on_start_record)
        self.btn_stop_rec.clicked.connect(self.on_stop_record)
        self.btn_snapshot.clicked.connect(self.on_save_snapshot)

        self.btn_quit.clicked.connect(self.close)
        self.btn_change_dir.clicked.connect(self.on_change_dir)

        self.combo_tz.currentIndexChanged.connect(self.on_timezone_changed)

        # Timer (główna pętla odświeżania obrazu)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.on_tick)
        self.timer.start(100)

        # Timer do okresowego sprawdzania NTP/DB
        self.net_timer = QTimer(self)
        self.net_timer.setTimerType(Qt.CoarseTimer)
        self.net_timer.timeout.connect(self._check_network_and_db)
        self.net_timer.start(5000)

        # Na start
        self._apply_timezone_from_ui()
        self._check_network_and_db()

    def _choose_output_dir(self) -> str:
        default = os.path.abspath(DEFAULT_OUTPUT_DIR)
        dlg_dir = QFileDialog.getExistingDirectory(
            self,
            "Wybierz folder do zapisu CSV/JSON/AVI",
            default
        )
        if dlg_dir:
            return dlg_dir
        return default

    # Strefa czasowa

    def on_timezone_changed(self, idx: int):
        self._apply_timezone_from_ui()

    def _apply_timezone_from_ui(self):
        idx = self.combo_tz.currentIndex()
        if idx < 0:
            return
        tz_name = self.combo_tz.itemData(idx)
        if not tz_name:
            return
        self.current_timezone_name = tz_name
        self.rec.set_timezone(tz_name)
        self.status.showMessage(f"Ustawiono strefę czasową: {tz_name}", 5000)

    # Zmiana katalogu

    def on_change_dir(self):
        new_dir = self._choose_output_dir()
        if new_dir:
            self.output_dir = new_dir
            self.lbl_output_dir.setText(self.output_dir)
            self.rec.set_output_dir(self.output_dir)
            self.status.showMessage(f"Zmieniono folder wyjściowy: {self.output_dir}", 5000)

    # Status NTP / DB

    def _check_network_and_db(self):
        ntp_ok = check_ntp_available()
        db_ok = check_db_connection()

        self.lbl_ntp_status.setText(f"NTP: {'OK' if ntp_ok else 'BRAK'}")
        self.lbl_ntp_status.setStyleSheet(
            f"color: {'green' if ntp_ok else 'red'}; font-weight: bold;"
        )

        self.lbl_db_status.setText(f"DB (PostgreSQL): {'OK' if db_ok else 'BRAK'}")
        self.lbl_db_status.setStyleSheet(
            f"color: {'green' if db_ok else 'red'}; font-weight: bold;"
        )

        msg = f"Status NTP: {'OK' if ntp_ok else 'BRAK'}, DB: {'OK' if db_ok else 'BRAK'}"
        self.status.showMessage(msg, 8000)

    # ROI / TRACKER

    def on_set_roi_slot(self, idx: int):
        new_rect = getattr(self.view, "last_drawn_rect_img", None)
        if new_rect is None:
            QMessageBox.information(
                self,
                "ROI",
                "Brak ROI - narysuj prostokąt na obrazie (myszką) i kliknij ponownie."
            )
            return
        self.roi_rects[idx] = new_rect
        self.view.clearRubber()

    def on_clear_roi(self, idx: int):
        self.trackers[idx].reset()
        self.roi_rects[idx] = None
        self.status.showMessage(f"ROI {idx+1} usunięte.", 4000)

    def on_start_track(self, idx: int):
        if self.roi_rects[idx] is None:
            new_rect = getattr(self.view, "last_drawn_rect_img", None)
            if new_rect is not None:
                self.roi_rects[idx] = new_rect
                self.view.clearRubber()

        rect = self.roi_rects[idx]
        if rect is None:
            QMessageBox.warning(self, "Tracker", f"ROI {idx+1} nie jest ustawione.")
            return

        preview_bgr, _ = self.cap.get_frames()
        if preview_bgr is None:
            QMessageBox.warning(self, "Kamera", "Brak klatki z kamery.")
            return

        bbox = (rect.x(), rect.y(), rect.width(), rect.height())
        ok = self.trackers[idx].init_on(preview_bgr, bbox=bbox)
        if not ok:
            QMessageBox.warning(self, "Tracker", f"Nie można uruchomić trackera dla ROI {idx+1}.")

    def on_stop_track(self, idx: int):
        self.trackers[idx].reset()
        QMessageBox.information(self, "Tracker", f"Śledzenie ROI {idx+1} wyłączone.")

    # POMIAR

    def on_start_measure(self):
        if self.is_measuring:
            return
        self.rec.start_session()
        if not self.rec.measuring:
            QMessageBox.warning(self, "Pomiary", "Nie udało się rozpocząć sesji pomiarowej.")
            return
        self.is_measuring = True
        self.label_meas.setText("MEAS: ON")
        self._last_logged_seq = -1

    def on_stop_measure(self):
        if not self.is_measuring:
            return
        self.is_measuring = False
        self.label_meas.setText("MEAS: OFF")
        self.rec.stop_session()

    # NAGRYWANIE WIDEO

    def on_start_record(self):
        if self.is_recording:
            return
        preview_bgr, _ = self.cap.get_frames()
        if preview_bgr is None:
            QMessageBox.warning(self, "Kamera", "Brak klatki z kamery.")
            return

        self.rec.start_video(preview_bgr.shape)
        if not self.rec.recording:
            QMessageBox.warning(self, "Nagrywanie", "Nie udało się rozpocząć nagrywania wideo.")
            return

        self.is_recording = True
        self.label_rec.setText("REC: ON")

    def on_stop_record(self):
        if not self.is_recording:
            return
        self.is_recording = False
        self.label_rec.setText("REC: OFF")
        self.rec.stop_video()

    def on_save_snapshot(self):
        preview_bgr, thermo_float = self.cap.get_frames()
        if preview_bgr is None:
            QMessageBox.warning(self, "Kamera", "Brak klatki z kamery.")
            return

        frame_show = preview_bgr.copy()

        # Rysowanie ROI
        colors = [
            (0, 255, 0),  # ROI1 – zielony (BGR)
            (255, 0, 0),  # ROI2 – niebieski
            (0, 0, 255),  # ROI3 – czerwony
        ]
        for idx, rect in enumerate(self.roi_rects):
            if rect is None:
                continue
            cv2.rectangle(
                frame_show,
                (rect.x(), rect.y()),
                (rect.x() + rect.width(), rect.y() + rect.height()),
                colors[idx],
                1,
            )

        # Temperatura w każdym ROI
        if thermo_float is not None:
            temps = self._roi_mean_temps(thermo_float)
        else:
            temps = [None, None, None]

        # Napisy z temperaturami w rogach ROI
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.2
        thickness = 1
        color_text = (255, 255, 255)  # biały

        for idx, rect in enumerate(self.roi_rects):
            if rect is None:
                continue
            t = temps[idx]
            text = "— C" if t is None else f"{t:.1f} C"
            x = rect.x()
            y = rect.y()
            text_pos = (x + 3, y + 12)
            cv2.putText(
                frame_show,
                text,
                text_pos,
                font,
                font_scale,
                color_text,
                thickness,
                cv2.LINE_AA,
            )

        # Czas w aktualnie wybranej strefie czasowej
        try:
            tz = zi.ZoneInfo(self.current_timezone_name)
        except Exception:
            tz = None

        now = datetime.datetime.now(tz) if tz else datetime.datetime.now()
        now = now.replace(microsecond=0)
        ts = now.strftime("%Y-%m-%d_%H-%M-%S")

        if getattr(self.rec, "measuring", False) and getattr(self.rec, "measure_base", None):
            base_name = f"{self.rec.measure_base}_IMG_{ts}"
        else:
            base_name = f"{ts}_IMG"

        filename = f"{base_name}.png"
        out_path = os.path.join(self.output_dir, filename)

        ok = cv2.imwrite(out_path, frame_show)
        if not ok:
            QMessageBox.warning(self, "Zapis zdjęcia", "Nie udało się zapisać pliku obrazu.")
            return

        self.status.showMessage(f"Zapisano zdjęcie: {out_path}", 5000)

    # TEMPERATURY

    def _roi_mean_temps(self, thermo_float):
        temps = []
        for rect in self.roi_rects:
            if rect is None:
                temps.append(None)
                continue

            x = rect.x()
            y = rect.y()
            w = rect.width()
            h = rect.height()

            x0 = max(0, x)
            y0 = max(0, y)
            x1 = min(thermo_float.shape[1], x + w)
            y1 = min(thermo_float.shape[0], y + h)

            if x1 <= x0 or y1 <= y0:
                temps.append(None)
                continue

            roi = thermo_float[y0:y1, x0:x1]
            mean_temp = float(np.mean(roi))
            temps.append(mean_temp)

        return temps

    # PĘTLA GŁÓWNA

    def on_tick(self):
        preview_bgr, thermo_float = self.cap.get_frames()
        if preview_bgr is None or thermo_float is None:
            return

        frame_show = preview_bgr.copy()
        seq = self.cap.frame_seq()

        colors = [
            (0, 255, 0),  # ROI1 – zielony (BGR)
            (255, 0, 0),  # ROI2 – niebieski
            (0, 0, 255),  # ROI3 – czerwony
        ]

        # Rysowanie trackerów / statycznych ROI
        for idx in range(3):
            tr = self.trackers[idx]

            if tr.active:
                ok, bbox = tr.update(preview_bgr)
                if ok and bbox is not None:
                    x, y, w, h = bbox
                    cv2.rectangle(frame_show, (x, y), (x + w, y + h), colors[idx], 1)
                    self.roi_rects[idx] = QRect(x, y, w, h)
                else:
                    tr.reset()
            else:
                rect = self.roi_rects[idx]
                if rect is not None:
                    cv2.rectangle(
                        frame_show,
                        (rect.x(), rect.y()),
                        (rect.x() + rect.width(), rect.y() + rect.height()),
                        colors[idx],
                        1,
                    )

        # Średnie temperatury
        temps = self._roi_mean_temps(thermo_float)

        # Napisy z temperaturami w rogach ROI
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.2
        thickness = 1
        color_text = (255, 255, 255)  # biały

        for idx, rect in enumerate(self.roi_rects):
            if rect is None:
                continue
            t = temps[idx]
            text = "— C" if t is None else f"{t:.1f} C"
            x = rect.x()
            y = rect.y()
            text_pos = (x + 3, y + 12)
            cv2.putText(
                frame_show,
                text,
                text_pos,
                font,
                font_scale,
                color_text,
                thickness,
                cv2.LINE_AA,
            )

        if self.is_measuring and seq != self._last_logged_seq:
            self.rec.log_sample_multi(temps)
            self._last_logged_seq = seq

        def fmt_t(val):
            return "—" if val is None else f"{val:.2f} C"

        self.label_temp.setText(
            f"ROI1: {fmt_t(temps[0])} | ROI2: {fmt_t(temps[1])} | ROI3: {fmt_t(temps[2])}"
        )

        # Zapis wideo
        if self.is_recording and self.rec.recording:
            self.rec.write_frame(frame_show)

        # Wyświetlenie na ekranie
        self.view.setFrame(bgr_to_qimage(frame_show))

    # ZAMKNIĘCIE

    def closeEvent(self, event: QCloseEvent):
        # zatrzymaj trackery
        for trk in self.trackers:
            trk.reset()

        # sesja pomiarowa
        if self.is_measuring and getattr(self.rec, "measuring", False):
            try:
                self.rec.mark_aborted()
            except Exception:
                self.rec.stop_session()
            self.is_measuring = False

        # nagrywanie wideo
        if self.is_recording and getattr(self.rec, "recording", False):
            self.rec.stop_video()
            self.is_recording = False

        # kamera
        self.cap.stop()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

