from PySide6.QtWidgets import QLabel, QRubberBand, QSizePolicy
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import QPixmap, QImage
import math

class VideoView(QLabel):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMouseTracking(True)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(960, 540)

        self._rubber = QRubberBand(QRubberBand.Rectangle, self)
        self._drag_origin = None
        self._drag_active = False

        self._last_frame_qimage = None
        self._scaled_pixmap = None

        self.last_drawn_rect_img = None

    def setFrame(self, qimg: QImage):
        self._last_frame_qimage = qimg
        self._rescale_and_update()

    def _rescale_and_update(self):
        if self._last_frame_qimage is None:
            return

        pm = QPixmap.fromImage(self._last_frame_qimage)
        target_size = self.contentsRect().size()
        if target_size.width() <= 0 or target_size.height() <= 0:
            return

        pm_scaled = pm.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._scaled_pixmap = pm_scaled
        self.setPixmap(pm_scaled)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._rescale_and_update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._scaled_pixmap is not None:
            self._drag_origin = ev.pos()
            self._drag_active = True
            self._rubber.setGeometry(QRect(self._drag_origin, self._drag_origin))
            self._rubber.show()

    def mouseMoveEvent(self, ev):
        if self._drag_active and self._drag_origin is not None:
            rect_widget = QRect(self._drag_origin, ev.pos()).normalized()
            self._rubber.setGeometry(rect_widget)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._drag_active:
            self._drag_active = False
            self._rubber.hide()

            rect_widget = QRect(self._drag_origin, ev.pos()).normalized()
            self._drag_origin = None

            img_rect = self._widget_rect_to_image_rect(rect_widget)
            self.last_drawn_rect_img = img_rect

    def clearRubber(self):
        self.last_drawn_rect_img = None
        self._rubber.hide()
        self._drag_origin = None
        self._drag_active = False

    def _calc_view_params(self):
        if self._last_frame_qimage is None:
            return None

        img_w = self._last_frame_qimage.width()
        img_h = self._last_frame_qimage.height()

        cr = self.contentsRect()
        lab_w = cr.width()
        lab_h = cr.height()

        if img_w <= 0 or img_h <= 0 or lab_w <= 0 or lab_h <= 0:
            return None

        scale = min(lab_w / img_w, lab_h / img_h)
        disp_w = img_w * scale
        disp_h = img_h * scale

        off_x = cr.x() + 0.5 * (lab_w - disp_w)
        off_y = cr.y() + 0.5 * (lab_h - disp_h)

        return (scale, off_x, off_y, img_w, img_h)

    def _widget_point_to_image_point(self, pt_widget: QPoint):
        params = self._calc_view_params()
        if params is None:
            return None
        scale, off_x, off_y, img_w, img_h = params

        x_img_f = (pt_widget.x() - off_x) / scale
        y_img_f = (pt_widget.y() - off_y) / scale

        x_img = max(0, min(int(math.floor(x_img_f)), img_w - 1))
        y_img = max(0, min(int(math.floor(y_img_f)), img_h - 1))
        return (x_img, y_img)

    def _widget_rect_to_image_rect(self, rect_widget: QRect):
        p1 = self._widget_point_to_image_point(rect_widget.topLeft())
        p2 = self._widget_point_to_image_point(rect_widget.bottomRight())
        if p1 is None or p2 is None:
            return None

        x1, y1 = p1
        x2, y2 = p2

        x_min = min(x1, x2)
        y_min = min(y1, y2)
        x_max = max(x1, x2)
        y_max = max(y1, y2)

        w = max(1, (x_max - x_min + 1))
        h = max(1, (y_max - y_min + 1))

        return QRect(x_min, y_min, w, h)
