import cv2

def create_tracker():
    try:
        return cv2.legacy.TrackerCSRT_create()
    except Exception:
        pass
    try:
        return cv2.legacy.TrackerKCF_create()
    except Exception:
        pass
    raise RuntimeError("Zainstaluj opencv-contrib-python.")

class TrackerManager:
    def __init__(self):
        self.tracker = None
        self.bbox = None
        self.active = False

    def reset(self):
        self.tracker = None
        self.bbox = None
        self.active = False

    def init_on(self, frame_bgr, bbox=None):
        if bbox is None:
            return False
        x, y, w, h = bbox
        H, W = frame_bgr.shape[:2]
        x = max(0, min(int(x), W-1)); y = max(0, min(int(y), H-1))
        w = max(1, min(int(w), W-x)); h = max(1, min(int(h), H-y))
        bbox = (x, y, w, h)
        self.tracker = create_tracker()
        ok = self.tracker.init(frame_bgr, bbox)
        self.active = bool(ok)
        self.bbox = bbox if ok else None
        return ok

    def update(self, frame_bgr):
        if not self.tracker:
            return False, None
        ok, bb = self.tracker.update(frame_bgr)
        if ok:
            self.bbox = tuple(map(int, bb))
            self.active = True
        else:
            self.active = False
        return ok, self.bbox