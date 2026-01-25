import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QLineEdit, QFileDialog,
    QMessageBox, QGroupBox, QFormLayout, QSizePolicy,
    QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt

from plottingwidget import PlotCanvas
from zoneinfo import ZoneInfo
import zoneinfo as zi 

try:
    from tzlocal import get_localzone_name
except ImportError:
    get_localzone_name = None


def build_timezone_items(system_tz: str):
    try:
        if hasattr(zi, "available_timezones"):
            all_tz = zi.available_timezones()
        else:
            raise AttributeError
    except Exception:
        all_tz = {
            "UTC",
            "Europe/Warsaw",
            "Europe/Berlin",
            "Europe/Paris",
            "Europe/London",
            "America/New_York",
            "America/Los_Angeles",
            "Asia/Tokyo",
            "Asia/Shanghai",
        }

    items = []
    for name in sorted(all_tz):
        parts = name.split("/")
        if len(parts) < 2:
            label = name
        else:
            city = parts[-1].replace("_", " ")
            label = f"{name} ({city})"
        items.append((name, label))

    if system_tz and system_tz not in [tz for tz, _ in items]:
        city = system_tz.split("/")[-1].replace("_", " ")
        items.insert(0, (system_tz, f"{system_tz} ({city}, systemowa)"))

    items.sort(key=lambda x: (0 if x[0] == system_tz else 1, x[0]))
    return items


class MainWindowViewer(QMainWindow):
    def __init__(self, db_client, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ROITempViewer")

        self.db = db_client

        if get_localzone_name is not None:
            try:
                system_tz = get_localzone_name()
            except Exception:
                system_tz = "Europe/Warsaw"
        else:
            system_tz = "Europe/Warsaw"

        self.current_timezone_name = system_tz
        self.tz_items = build_timezone_items(system_tz)

        self.sessions = []
        self.current_session_id = None
        self.current_session_start_utc = None  
        self.df_full = None      
        self.df_view = None      

        self.markers = []

        # GÓRA
        top_box = QGroupBox("Wybór pomiaru")
        top_layout = QGridLayout()

        self.combo_sessions = QComboBox()
        self.btn_refresh_sessions = QPushButton("Odśwież listę")
        self.lbl_db_size = QLabel("DB Size: ?")
        top_layout.addWidget(self.lbl_db_size, 0, 4)

        self.btn_delete_session = QPushButton("Usuń tę sesję z bazy")

        self.edit_t_from = QLineEdit()
        self.edit_t_to = QLineEdit()
        self.edit_t_from.setPlaceholderText("od (s)")
        self.edit_t_to.setPlaceholderText("do (s)")
        self.btn_apply_range = QPushButton("Zastosuj zakres")

        self.chk_roi1 = QCheckBox("ROI 1 (zielony)")
        self.chk_roi2 = QCheckBox("ROI 2 (niebieski)")
        self.chk_roi3 = QCheckBox("ROI 3 (czerwony)")
        self.chk_roi1.setChecked(True)
        self.chk_roi2.setChecked(True)
        self.chk_roi3.setChecked(True)

        self.combo_tz = QComboBox()
        for tz_id, label in self.tz_items:
            self.combo_tz.addItem(label, userData=tz_id)
        idx_default = 0
        for i in range(self.combo_tz.count()):
            if self.combo_tz.itemData(i) == self.current_timezone_name:
                idx_default = i
                break
        self.combo_tz.setCurrentIndex(idx_default)

        self.lbl_start_local = QLabel("Start sesji (lokalnie): -")

        self.edit_from_clock = QLineEdit()
        self.edit_from_clock.setPlaceholderText("HH:MM:SS")
        self.btn_apply_from_clock = QPushButton("Ustaw 'od' wg godziny")

        row_clock = QHBoxLayout()
        row_clock.addWidget(self.edit_from_clock)
        row_clock.addWidget(self.btn_apply_from_clock)

        # układ górny
        top_layout.addWidget(QLabel("Sesja:"), 0, 0)
        top_layout.addWidget(self.combo_sessions, 0, 1)
        top_layout.addWidget(self.btn_refresh_sessions, 0, 2)
        top_layout.addWidget(self.btn_delete_session, 0, 3)

        row_range = QHBoxLayout()
        row_range.addWidget(self.edit_t_from)
        row_range.addWidget(QLabel("→"))
        row_range.addWidget(self.edit_t_to)
        row_range.addWidget(self.btn_apply_range)
        top_layout.addWidget(QLabel("Zakres czasu [s]:"), 1, 0)
        top_layout.addLayout(row_range, 1, 1, 1, 3)

        row_roi = QHBoxLayout()
        row_roi.addWidget(self.chk_roi1)
        row_roi.addWidget(self.chk_roi2)
        row_roi.addWidget(self.chk_roi3)
        top_layout.addLayout(row_roi, 2, 0, 1, 4)

        top_layout.addWidget(QLabel("Strefa czasowa wyświetlania:"), 3, 0)
        top_layout.addWidget(self.combo_tz, 3, 1, 1, 3)

        top_layout.addWidget(self.lbl_start_local, 4, 0)
        top_layout.addLayout(row_clock, 4, 1, 1, 3)

        top_box.setLayout(top_layout)

        # ŚRODEK 
        middle_layout = QHBoxLayout()

        self.plot_canvas = PlotCanvas()
        self.plot_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        stats_box = QGroupBox("Informacje")
        stats_form = QFormLayout()
        self.lbl_stats_roi1 = QLabel("-")
        self.lbl_stats_roi2 = QLabel("-")
        self.lbl_stats_roi3 = QLabel("-")
        stats_form.addRow(QLabel("ROI 1:"), self.lbl_stats_roi1)
        stats_form.addRow(QLabel("ROI 2:"), self.lbl_stats_roi2)
        stats_form.addRow(QLabel("ROI 3:"), self.lbl_stats_roi3)

        self.lbl_point_title = QLabel("Wartości:")
        self.lbl_point_time = QLabel("-")
        self.lbl_point_roi1 = QLabel("-")
        self.lbl_point_roi2 = QLabel("-")
        self.lbl_point_roi3 = QLabel("-")

        stats_form.addRow(self.lbl_point_title)
        stats_form.addRow(QLabel("Czas [s]:"), self.lbl_point_time)
        stats_form.addRow(QLabel("ROI 1:"), self.lbl_point_roi1)
        stats_form.addRow(QLabel("ROI 2:"), self.lbl_point_roi2)
        stats_form.addRow(QLabel("ROI 3:"), self.lbl_point_roi3)

        self.marker_list = QListWidget()
        self.btn_delete_marker = QPushButton("Usuń wybrany marker")
        self.btn_clear_markers = QPushButton("Usuń wszystkie markery")

        stats_form.addRow(QLabel("Markery:"), self.marker_list)
        stats_form.addRow(self.btn_delete_marker)
        stats_form.addRow(self.btn_clear_markers)

        stats_box.setLayout(stats_form)

        middle_layout.addWidget(self.plot_canvas, stretch=1)
        middle_layout.addWidget(stats_box, stretch=0)

        # DÓŁ
        bottom_box = QGroupBox("Eksport")
        bottom_layout = QHBoxLayout()
        self.btn_export_png = QPushButton("Zapisz wykres jako PNG")
        self.btn_export_csv = QPushButton("Zapisz CSV z zakresu")
        self.btn_export_markers_csv = QPushButton("Zapisz markery do CSV")
        bottom_layout.addWidget(self.btn_export_png)
        bottom_layout.addWidget(self.btn_export_csv)
        bottom_layout.addWidget(self.btn_export_markers_csv)
        bottom_box.setLayout(bottom_layout)

        # UKŁAD GŁÓWNY
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.addWidget(top_box)
        main_layout.addLayout(middle_layout)
        main_layout.addWidget(bottom_box)
        self.setCentralWidget(central)

        # sygnały
        self.btn_refresh_sessions.clicked.connect(self.load_sessions)
        self.combo_sessions.currentIndexChanged.connect(self.on_session_selected)
        self.btn_apply_range.clicked.connect(self.apply_range_and_update)
        self.btn_delete_session.clicked.connect(self.on_delete_session)

        self.chk_roi1.stateChanged.connect(self.update_plot_and_stats)
        self.chk_roi2.stateChanged.connect(self.update_plot_and_stats)
        self.chk_roi3.stateChanged.connect(self.update_plot_and_stats)

        self.btn_export_png.clicked.connect(self.export_png)
        self.btn_export_csv.clicked.connect(self.export_csv)
        self.btn_export_markers_csv.clicked.connect(self.export_markers_csv)

        self.btn_apply_from_clock.clicked.connect(self.apply_from_clock)
        self.combo_tz.currentIndexChanged.connect(self.on_timezone_changed)

        self.btn_delete_marker.clicked.connect(self.on_delete_selected_marker)
        self.btn_clear_markers.clicked.connect(self.on_clear_all_markers)

        self.plot_canvas.mpl_connect("motion_notify_event", self.on_plot_hover)
        self.plot_canvas.mpl_connect("button_press_event", self.on_plot_click)
        self.plot_canvas.mpl_connect("figure_leave_event", self.on_plot_leave)

        self.load_sessions()

    # strefy czasowe

    def _to_local(self, dt_utc: datetime) -> datetime | None:
        if dt_utc is None:
            return None
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        try:
            tz = ZoneInfo(self.current_timezone_name)
        except Exception:
            tz = timezone.utc
        return dt_utc.astimezone(tz)

    def on_timezone_changed(self, idx: int):
        tz_name = self.combo_tz.itemData(idx)
        if not tz_name:
            return
        self.current_timezone_name = tz_name
        self._refresh_session_labels()
        self._update_start_label()

    # DB

    def load_sessions(self):
        try:
            self.sessions = self.db.get_sessions()
        except Exception as e:
            QMessageBox.critical(self, "Błąd DB", f"Nie mogżna pobrać sesji:\n{e}")
            return

        try:
            db_size_txt = self.db.get_db_size_pretty()
            mb = self._parse_size_to_mb(db_size_txt)
            if mb < 400:
                self.lbl_db_size.setStyleSheet("color: green;")
            else:
                self.lbl_db_size.setStyleSheet("color: red;")
            self.lbl_db_size.setText(f"DB Size: {db_size_txt}")
        except Exception:
            self.lbl_db_size.setStyleSheet("")
            self.lbl_db_size.setText("DB Size: ?")

        self.combo_sessions.blockSignals(True)
        self.combo_sessions.clear()
        self._refresh_session_labels()
        self.combo_sessions.blockSignals(False)

        if self.combo_sessions.count() > 0:
            self.combo_sessions.setCurrentIndex(0)
            self.on_session_selected()
        else:
            self.current_session_id = None
            self.current_session_start_utc = None
            self.lbl_start_local.setText("Start sesji (lokalnie): -")
            self.df_full = None
            self.df_view = None
            self.update_plot_and_stats()

    def _refresh_session_labels(self):
        self.combo_sessions.blockSignals(True)
        self.combo_sessions.clear()
        for s in self.sessions:
            sid = s["session_id"]
            st_utc = s["started_utc"]
            ab = s["aborted"]

            if st_utc is None:
                label = "(brak daty)"
            else:
                st_local = self._to_local(st_utc)
                label = st_local.strftime("%Y-%m-%d %H:%M:%S")
                if ab:
                    label += " (aborted)"

            self.combo_sessions.addItem(label, userData=sid)
        self.combo_sessions.blockSignals(False)

    def on_session_selected(self):
        idx = self.combo_sessions.currentIndex()
        if idx < 0:
            return
        sid = self.combo_sessions.itemData(idx)
        self.current_session_id = sid

        s = self._get_current_session()
        if s and s.get("started_utc"):
            self.current_session_start_utc = s["started_utc"]
        else:
            self.current_session_start_utc = None

        self._update_start_label()

        if not sid:
            return

        try:
            df = self.db.get_samples(sid)
        except Exception as e:
            QMessageBox.critical(self, "Błąd DB", f"Nie można pobrać próbek:\n{e}")
            return

        self.df_full = df
        self.edit_t_from.clear()
        self.edit_t_to.clear()
        self.edit_from_clock.clear()

        self.on_clear_all_markers()

        self.apply_range_and_update()

    def _update_start_label(self):
        if not self.current_session_start_utc:
            self.lbl_start_local.setText("Start sesji (lokalnie): -")
            return
        st_local = self._to_local(self.current_session_start_utc)
        self.lbl_start_local.setText(
            f"Start sesji (lokalnie, {self.current_timezone_name}): "
            f"{st_local.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    def on_delete_session(self):
        if not self.current_session_id:
            return

        ans = QMessageBox.question(
            self,
            "Usuń sesję",
            "Czy na pewno chcesz usunąć tę sesję wraz z próbkami?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return

        try:
            self.db.delete_session(self.current_session_id)
        except Exception as e:
            QMessageBox.critical(self, "Błąd DB", f"Nie można usunąć sesji:\n{e}")
            return

        self.load_sessions()

    # ZAKRES

    def apply_range_and_update(self):
        if self.df_full is None or len(self.df_full) == 0:
            self.df_view = None
            self.update_plot_and_stats()
            return

        df = self.df_full
        t_from_txt = self.edit_t_from.text().strip()
        t_to_txt = self.edit_t_to.text().strip()

        try:
            if t_from_txt != "":
                t_from = float(t_from_txt)
            else:
                t_from = df["t_s"].min()
            if t_to_txt != "":
                t_to = float(t_to_txt)
            else:
                t_to = df["t_s"].max()
        except ValueError:
            QMessageBox.warning(self, "Zakres", "Podaj wartości liczbowe (sekundy).")
            return

        mask = (df["t_s"] >= t_from) & (df["t_s"] <= t_to)
        df_sub = df.loc[mask].copy()

        if df_sub.empty:
            QMessageBox.information(self, "Zakres", "Brak danych w tym przedziale.")
            self.df_view = None
        else:
            self.df_view = df_sub

        self.on_clear_all_markers()

        self.update_plot_and_stats()

    def apply_from_clock(self):
        if not self.current_session_start_utc:
            QMessageBox.information(self, "Czas sesji", "Brak informacji o starcie sesji.")
            return

        txt = self.edit_from_clock.text().strip()
        if not txt:
            QMessageBox.information(self, "Czas sesji", "Podaj czas w formacie HH:MM:SS.")
            return

        try:
            t_in = datetime.strptime(txt, "%H:%M:%S").time()
        except ValueError:
            QMessageBox.warning(self, "Czas sesji", "Nieprawidłowy format. Użyj HH:MM:SS.")
            return

        start_local = self._to_local(self.current_session_start_utc)
        if start_local is None:
            QMessageBox.warning(self, "Czas sesji", "Nie można przeliczyć czasu startu.")
            return

        tz = start_local.tzinfo
        target_local = datetime.combine(start_local.date(), t_in, tzinfo=tz)

        if target_local < start_local:
            target_local = target_local + timedelta(days=1)

        t_from = (target_local - start_local).total_seconds()

        if self.df_full is not None and len(self.df_full) > 0:
            t_min = float(self.df_full["t_s"].min())
            t_max = float(self.df_full["t_s"].max())
            if t_from < t_min:
                t_from = t_min
            if t_from > t_max:
                t_from = t_max

        self.edit_t_from.setText(f"{t_from:.3f}")
        self.apply_range_and_update()

    # RYSOWANIE

    def update_plot_and_stats(self):
        if self.df_view is None or len(self.df_view) == 0:
            self.plot_canvas.ax.clear()
            self.plot_canvas.ax.grid(True)
            self.plot_canvas.ax.set_xlabel("Czas [s]")
            self.plot_canvas.ax.set_ylabel("Temperatura [°C]")
            self.plot_canvas.draw()
            self.lbl_stats_roi1.setText("-")
            self.lbl_stats_roi2.setText("-")
            self.lbl_stats_roi3.setText("-")
            self._clear_point_labels()
            self.on_clear_all_markers()
            return

        df = self.df_view
        show_1 = self.chk_roi1.isChecked()
        show_2 = self.chk_roi2.isChecked()
        show_3 = self.chk_roi3.isChecked()

        series_to_plot = {}
        if show_1 and "temp_r1" in df.columns:
            series_to_plot["ROI1"] = (df["temp_r1"], "green")
        if show_2 and "temp_r2" in df.columns:
            series_to_plot["ROI2"] = (df["temp_r2"], "blue")
        if show_3 and "temp_r3" in df.columns:
            series_to_plot["ROI3"] = (df["temp_r3"], "red")

        self.plot_canvas.plot_data(df["t_s"], series_to_plot)

        self.lbl_stats_roi1.setText(
            self._roi_stats_text(df["t_s"], df["temp_r1"]) if show_1 else "-"
        )
        self.lbl_stats_roi2.setText(
            self._roi_stats_text(df["t_s"], df["temp_r2"]) if show_2 else "-"
        )
        self.lbl_stats_roi3.setText(
            self._roi_stats_text(df["t_s"], df["temp_r3"]) if show_3 else "-"
        )

        for marker in self.markers:
            t = marker["t"]
            line = self.plot_canvas.add_marker(t, color="black", linestyle="--")
            marker["line"] = line

    def _roi_stats_text(self, t_s_series, temp_series):
        temps = temp_series.to_numpy(dtype=float)
        times = t_s_series.to_numpy(dtype=float)
        mask = ~np.isnan(temps)
        if not np.any(mask):
            return "-"
        temps_valid = temps[mask]
        times_valid = times[mask]

        idx_max = np.argmax(temps_valid)
        max_temp = temps_valid[idx_max]
        max_time = times_valid[idx_max]

        idx_min = np.argmin(temps_valid)
        min_temp = temps_valid[idx_min]
        min_time = temps_valid[idx_min]

        return (
            f"MAX {max_temp:.2f} °C w {max_time:.3f} s"
            f"\nMIN {min_temp:.2f} °C w {min_time:.3f} s"
        )

    # MARKERY

    def on_plot_hover(self, event):
        if event.xdata is None:
            return
        if self.df_view is None or len(self.df_view) == 0:
            return

        t = float(event.xdata)
        self._update_point_labels(t, from_hover=True)

    def on_plot_click(self, event):
        if event.xdata is None:
            return
        if self.df_view is None or len(self.df_view) == 0:
            return

        t = float(event.xdata)

        df = self.df_view
        times = df["t_s"].to_numpy(dtype=float)
        idx = int(np.argmin(np.abs(times - t)))
        row = df.iloc[idx]
        t_real = float(times[idx])

        t1 = row.get("temp_r1")
        t2 = row.get("temp_r2")
        t3 = row.get("temp_r3")

        line = self.plot_canvas.add_marker(t_real, color="black", linestyle="--")

        marker_info = {"t": t_real, "temps": (t1, t2, t3), "line": line}
        self.markers.append(marker_info)

        def fmt(v):
            if pd.isna(v):
                return "-"
            return f"{float(v):.2f} °C"

        item_text = (
            f"t = {t_real:.3f} s | "
            f"ROI1: {fmt(t1)} | ROI2: {fmt(t2)} | ROI3: {fmt(t3)}"
        )
        item = QListWidgetItem(item_text)
        item.setData(Qt.UserRole, marker_info)
        self.marker_list.addItem(item)

    def on_plot_leave(self, event):
        self._clear_point_labels()

    def _update_point_labels(self, t: float, from_hover: bool = False):
        if self.df_view is None or len(self.df_view) == 0:
            return

        df = self.df_view
        times = df["t_s"].to_numpy(dtype=float)
        idx = int(np.argmin(np.abs(times - t)))
        row = df.iloc[idx]
        t_real = float(times[idx])

        def _fmt(v):
            if pd.isna(v):
                return "-"
            return f"{v:.2f} °C"

        self.lbl_point_time.setText(f"{t_real:.3f} s")
        self.lbl_point_roi1.setText(_fmt(row.get("temp_r1")))
        self.lbl_point_roi2.setText(_fmt(row.get("temp_r2")))
        self.lbl_point_roi3.setText(_fmt(row.get("temp_r3")))

    def _clear_point_labels(self):
        self.lbl_point_time.setText("-")
        self.lbl_point_roi1.setText("-")
        self.lbl_point_roi2.setText("-")
        self.lbl_point_roi3.setText("-")

    def on_delete_selected_marker(self):
        selected_items = self.marker_list.selectedItems()
        if not selected_items:
            return

        for item in selected_items:
            marker_info = item.data(Qt.UserRole)
            if marker_info and "line" in marker_info:
                self.plot_canvas.remove_marker(marker_info["line"])
            row = self.marker_list.row(item)
            self.marker_list.takeItem(row)
            try:
                self.markers.remove(marker_info)
            except ValueError:
                pass

    def on_clear_all_markers(self):
        self.plot_canvas.clear_markers()
        self.marker_list.clear()
        self.markers = []

    # EKSPORT 

    def export_png(self):
        if self.df_view is None or len(self.df_view) == 0:
            QMessageBox.information(self, "Eksport PNG", "Brak danych.")
            return
        fn, _ = QFileDialog.getSaveFileName(
            self, "Zapisz wykres jako PNG", "wykres.png", "PNG (*.png)"
        )
        if not fn:
            return
        try:
            self.plot_canvas.save_png(fn)
            QMessageBox.information(self, "Eksport PNG", f"Zapisano do:\n{fn}")
        except Exception as e:
            QMessageBox.critical(self, "Eksport PNG", f"Błąd zapisu:\n{e}")

    def export_csv(self):
        if self.df_view is None or len(self.df_view) == 0:
            QMessageBox.information(self, "Eksport CSV", "Brak danych.")
            return
        fn, _ = QFileDialog.getSaveFileName(
            self, "Zapisz dane jako CSV", "zakres.csv", "CSV (*.csv)"
        )
        if not fn:
            return
        cols = ["t_s", "temp_r1", "temp_r2", "temp_r3"]
        df_out = self.df_view[cols].copy()
        try:
            df_out.to_csv(fn, index=False)
            QMessageBox.information(self, "Eksport CSV", f"Zapisano do:\n{fn}")
        except Exception as e:
            QMessageBox.critical(self, "Eksport CSV", f"Błąd zapisu:\n{e}")

    def export_markers_csv(self):
        if not self.markers:
            QMessageBox.information(self, "Eksport markerów", "Brak markerów do zapisania.")
            return

        fn, _ = QFileDialog.getSaveFileName(
            self, "Zapisz markery jako CSV", "markery.csv", "CSV (*.csv)"
        )
        if not fn:
            return

        rows = []
        for m in self.markers:
            t = m.get("t")
            t1, t2, t3 = m.get("temps", (None, None, None))
            rows.append(
                {
                    "t_s": t,
                    "temp_r1": t1,
                    "temp_r2": t2,
                    "temp_r3": t3,
                }
            )

        df_out = pd.DataFrame(rows, columns=["t_s", "temp_r1", "temp_r2", "temp_r3"])

        try:
            df_out.to_csv(fn, index=False)
            QMessageBox.information(self, "Eksport markerów", f"Zapisano do:\n{fn}")
        except Exception as e:
            QMessageBox.critical(self, "Eksport markerów", f"Błąd zapisu:\n{e}")

    def _parse_size_to_mb(self, txt: str) -> float:
        if not txt:
            return 0.0
        parts = txt.strip().split()
        if len(parts) < 2:
            return 0.0
        try:
            val = float(parts[0].replace(',', '.'))
        except ValueError:
            return 0.0
        unit = parts[1].lower()
        if unit.startswith('gb'):
            return val * 1024
        if unit.startswith('mb'):
            return val
        if unit.startswith('kb'):
            return val / 1024
        return val

    def _get_current_session(self):
        sid = self.current_session_id
        if not sid:
            return None
        for s in self.sessions:
            if s["session_id"] == sid:
                return s
        return None
