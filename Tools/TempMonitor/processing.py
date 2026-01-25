import numpy as np
import cv2
from PySide6.QtGui import QImage

def thermo_to_preview_bgr(thermo_float: np.ndarray) -> np.ndarray:
    norm = cv2.normalize(thermo_float, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return cv2.applyColorMap(norm, cv2.COLORMAP_JET)

def bgr_to_qimage(bgr: np.ndarray) -> QImage:
    rgb = bgr[..., ::-1].copy()
    h, w, ch = rgb.shape
    return QImage(rgb.data, w, h, ch*w, QImage.Format.Format_RGB888)