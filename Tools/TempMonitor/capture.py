import threading
import time
import numpy as np
from processing import thermo_to_preview_bgr
from seekcamera import (
    SeekCameraManager,
    SeekCameraIOType,
    SeekCameraFrameFormat,
    SeekCameraColorPalette,
    SeekCameraManagerEvent
)

class SeekCapture:

    def __init__(self):
        self.manager = None
        self.cam = None

        self.lock = threading.Lock()
        self.thermo_float = None
        self.preview_bgr = None

        self._seq = 0

        self._last_ts = 0.0

    def start(self):
        self.manager = SeekCameraManager(SeekCameraIOType.USB)
        self.manager.register_event_callback(self._on_event, None)

    def stop(self):
        try:
            if self.cam:
                self.cam.capture_session_stop()
        except Exception:
            pass
        self.cam = None

    def _on_event(self, camera, event_type, _status, _user):
        if event_type == SeekCameraManagerEvent.CONNECT:
            self._attach(camera)
        elif event_type == SeekCameraManagerEvent.DISCONNECT and self.cam is camera:
            self._detach()

    def _attach(self, camera):
        self.cam = camera
        try:
            camera.color_palette = SeekCameraColorPalette.TYRIAN
        except Exception:
            pass

        camera.register_frame_available_callback(self._on_frame, None)
        camera.capture_session_start(SeekCameraFrameFormat.THERMOGRAPHY_FLOAT)

    def _detach(self):
        try:
            if self.cam:
                self.cam.capture_session_stop()
        except Exception:
            pass

        self.cam = None
        with self.lock:
            self.thermo_float = None
            self.preview_bgr = None

    def _on_frame(self, camera, frame, _user):
        try:
            thermo = frame.thermography_float.data
            preview = thermo_to_preview_bgr(thermo)
            with self.lock:
                self.thermo_float = thermo
                self.preview_bgr = preview
                self._seq += 1
                self._last_ts = time.monotonic()
        except Exception:
            pass

    def get_frames(self):
        with self.lock:
            p = None if self.preview_bgr is None else self.preview_bgr.copy()
            t = None if self.thermo_float is None else self.thermo_float.copy()
        return p, t

    def frame_seq(self):
        with self.lock:
            return self._seq
