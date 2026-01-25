import os
import csv
import json
import time
import uuid
import datetime
import threading
import queue
import socket
import struct

import cv2
import psycopg2

from zoneinfo import ZoneInfo
from config import OUTPUT_DIR as DEFAULT_OUTPUT_DIR
from config import VIDEO_FPS


# Supabase (DB)
DB_CONN_STR = (
    "x"
    "y"
    "z"
)

# Czas z NTP

NTP_SERVER = "pool.ntp.org"
NTP_PORT = 123
NTP_DELTA = 2208988800 


def get_utc_now() -> datetime.datetime:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        msg = b"\x1b" + 47 * b"\0" 
        sock.sendto(msg, (NTP_SERVER, NTP_PORT))
        data, _addr = sock.recvfrom(48)
        if data and len(data) >= 48:
            unpacked = struct.unpack("!12I", data)
            tx_timestamp = unpacked[10] 
            unix_time = tx_timestamp - NTP_DELTA
            return datetime.datetime.utcfromtimestamp(unix_time)
    except Exception:
        pass

    return datetime.datetime.utcnow()


def check_ntp_available(timeout: float = 1.0) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        msg = b"\x1b" + 47 * b"\0"
        sock.sendto(msg, (NTP_SERVER, NTP_PORT))
        data, _addr = sock.recvfrom(48)
        return bool(data and len(data) >= 48)
    except Exception:
        return False


def check_db_connection(timeout: float = 3.0) -> bool:
    try:
        with psycopg2.connect(DB_CONN_STR, connect_timeout=int(timeout)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        return True
    except Exception as e:
        print("[DB] connection check failed:", e)
        return False


class _DBWorker(threading.Thread):
    def __init__(self, conn_str: str, batch_size: int = 200, flush_interval_s: float = 0.5):
        super().__init__(daemon=True)
        self.conn_str = conn_str
        self.batch_size = batch_size
        self.flush_interval_s = flush_interval_s

        self.q = queue.Queue()
        self.stop_flag = threading.Event()

        self._conn = None
        self._cur = None

    def run(self):
        buf = []
        last_flush = time.monotonic()

        while not self.stop_flag.is_set():
            try:
                item = self.q.get(timeout=0.1)
                buf.append(item)
            except queue.Empty:
                pass

            now = time.monotonic()
            should_flush = (len(buf) >= self.batch_size) or ((now - last_flush) >= self.flush_interval_s)

            if should_flush and buf:
                self._flush_batch(buf)
                buf.clear()
                last_flush = now

        if buf:
            self._flush_batch(buf)

        self._close_conn()

    def enqueue(self, session_id: str, t_s: float, t1, t2, t3):
        try:
            self.q.put_nowait((session_id, t_s, t1, t2, t3))
        except Exception as e:
            print("[DBW] enqueue failed:", e)

    def stop(self):
        self.stop_flag.set()

    def _ensure_conn(self):
        if self._conn is not None and self._cur is not None:
            return
        try:
            self._conn = psycopg2.connect(self.conn_str, connect_timeout=5)
            self._conn.autocommit = False
            self._cur = self._conn.cursor()
        except Exception as e:
            print("[DBW] connect failed:", e)
            self._conn = None
            self._cur = None

    def _close_conn(self):
        try:
            if self._cur:
                self._cur.close()
        except Exception:
            pass
        try:
            if self._conn:
                self._conn.close()
        except Exception:
            pass
        self._cur = None
        self._conn = None

    def _flush_batch(self, rows):
        self._ensure_conn()
        if not self._cur:
            print(f"[DBW] skip batch ({len(rows)} rows) – no connection")
            return
        try:
            self._cur.executemany(
                """
                INSERT INTO public.samples (session_id, t_s, temp_r1, temp_r2, temp_r3)
                VALUES (%s, %s, %s, %s, %s)
                """,
                rows
            )
            self._conn.commit()
        except Exception as e:
            print("[DBW] batch insert failed:", e)
            try:
                self._conn.rollback()
            except Exception:
                pass
            self._close_conn()
            self._ensure_conn()
            if self._cur:
                try:
                    self._cur.executemany(
                        """
                        INSERT INTO public.samples (session_id, t_s, temp_r1, temp_r2, temp_r3)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        rows
                    )
                    self._conn.commit()
                except Exception as e2:
                    print("[DBW] retry failed:", e2)
                    try:
                        self._conn.rollback()
                    except Exception:
                        pass
                    self._close_conn()


class SessionRecorder:
    def __init__(self, output_dir: str = DEFAULT_OUTPUT_DIR, timezone_name: str = "UTC", db_conn_str: str = DB_CONN_STR):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

        self.timezone_name = timezone_name

        # stan sesji
        self.measuring = False
        self.t0_mono = None
        self.measure_base = None

        # CSV
        self.csv_fh = None
        self.csv_wr = None
        self._csv_rows_since_flush = 0
        self._csv_flush_every = 10 

        # JSON
        self.json_path = None

        # wideo
        self.recording = False
        self.video_writer = None
        self.video_path = None
        self.video_size = None
        self.video_fps = VIDEO_FPS
        self.video_base = None

        # DB
        self.db_conn_str = db_conn_str
        self.session_id = None
        self.started_utc = None


        self._dbw = None  # type: _DBWorker | None

    # strefa czasowa

    def set_timezone(self, tz_name: str):
        self.timezone_name = tz_name

    def _to_local(self, utc_dt: datetime.datetime) -> datetime.datetime:
        try:
            tz = ZoneInfo(self.timezone_name)
        except Exception:
            tz = datetime.timezone.utc

        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=datetime.timezone.utc)
        return utc_dt.astimezone(tz)

    # POMIAR

    def _unique_name(self) -> str:
        utc_now = get_utc_now().replace(microsecond=0)
        local_now = self._to_local(utc_now)
        return local_now.strftime("%Y-%m-%d_%H-%M-%S")

    def start_session(self):
        if self.measuring:
            return

        base = self._unique_name()
        self.measure_base = base

        csv_path = os.path.join(self.output_dir, f"{base}.csv")
        json_path = os.path.join(self.output_dir, f"{base}.json")

        # CSV
        self.csv_fh = open(csv_path, "w", newline="", encoding="utf-8")
        self.csv_wr = csv.writer(self.csv_fh, delimiter=';', lineterminator='\n')
        self.csv_wr.writerow(["t_s", "temp_roi1_c", "temp_roi2_c", "temp_roi3_c"])
        self._csv_rows_since_flush = 0

        # JSON – metadane
        self.json_path = json_path
        self.started_utc = get_utc_now()
        started_local = self._to_local(self.started_utc)
        meta = {
            "session_id": None,
            "started_utc": self.started_utc.isoformat() + "Z",  
            "started_local": started_local.isoformat(),         
            "timezone_name": self.timezone_name,
            "aborted": False,
        }

        # SESSION_ID
        self.session_id = str(uuid.uuid4())
        meta["session_id"] = self.session_id

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        self.t0_mono = time.monotonic()
        self.measuring = True

        self._db_insert_session(self.session_id, self.started_utc, aborted=False)

        if self.db_conn_str:
            self._dbw = _DBWorker(self.db_conn_str, batch_size=200, flush_interval_s=0.5)
            self._dbw.start()

        print(f"[REC] start session {self.session_id} -> {csv_path}")

    def log_sample_multi(self, temps_c):
        if not self.measuring:
            return
        if self.csv_wr is None or self.t0_mono is None:
            return

        t_s = time.monotonic() - self.t0_mono

        t1 = temps_c[0] if len(temps_c) > 0 else None
        t2 = temps_c[1] if len(temps_c) > 1 else None
        t3 = temps_c[2] if len(temps_c) > 2 else None

        def f(v):
            if v is None:
                return ""
            return f"{v:.2f}".replace('.', ',')

        row = [f"{t_s:.3f}".replace('.', ','), f(t1), f(t2), f(t3)]
        self.csv_wr.writerow(row)
        self._csv_rows_since_flush += 1
        if self._csv_rows_since_flush >= self._csv_flush_every:
            try:
                self.csv_fh.flush()
                os.fsync(self.csv_fh.fileno())
            except Exception:
                pass
            self._csv_rows_since_flush = 0

        if self.session_id is not None and self._dbw is not None:
            self._dbw.enqueue(self.session_id, t_s, t1, t2, t3)

    def _finalize_csv(self):
        if self.csv_fh:
            try:
                self.csv_fh.flush()
                os.fsync(self.csv_fh.fileno())
            except Exception:
                pass
            try:
                self.csv_fh.close()
            except Exception:
                pass
        self.csv_fh = None
        self.csv_wr = None
        self._csv_rows_since_flush = 0

    def stop_session(self):
        if not self.measuring:
            return

        ended_utc = get_utc_now()
        ended_local = self._to_local(ended_utc)

        self._finalize_csv()

        # uzupełnienie JSON
        if self.json_path:
            try:
                with open(self.json_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
            meta["ended_utc"] = ended_utc.isoformat() + "Z"
            meta["ended_local"] = ended_local.isoformat()
            meta["aborted"] = False
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)

        if self._dbw is not None:
            self._dbw.stop()
            self._dbw.join(timeout=2.0)
            self._dbw = None
        if self.session_id is not None:
            self._db_update_session_end(self.session_id, ended_utc, aborted=False)

        self.measuring = False
        self.t0_mono = None
        self.measure_base = None
        self.session_id = None
        self.json_path = None

        print("[REC] stop session")

    def mark_aborted(self):
        if not self.measuring:
            return

        ended_utc = get_utc_now()
        ended_local = self._to_local(ended_utc)

        self._finalize_csv()

        if self.json_path:
            try:
                with open(self.json_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
            meta["ended_utc"] = ended_utc.isoformat() + "Z"
            meta["ended_local"] = ended_local.isoformat()
            meta["aborted"] = True
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)

        if self._dbw is not None:
            self._dbw.stop()
            self._dbw.join(timeout=2.0)
            self._dbw = None

        if self.session_id is not None:
            self._db_update_session_end(self.session_id, ended_utc, aborted=True)

        self.measuring = False
        self.t0_mono = None
        self.measure_base = None
        self.session_id = None
        self.json_path = None

        print("[REC] aborted session")

    # WIDEO

    def start_video(self, frame_shape):
        H, W = frame_shape[:2]
        self.video_size = (W, H)

        if self.measuring and self.measure_base:
            base = f"{self.measure_base}_VIDEO"
        else:
            base = self._unique_name()

        self.video_base = base
        self.video_path = os.path.join(self.output_dir, f"{base}.avi")

        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        self.video_writer = cv2.VideoWriter(self.video_path, fourcc, self.video_fps, self.video_size)

        if not self.video_writer.isOpened():
            print(f"[VIDEO] Nie można otworzyć VideoWriter dla {self.video_path} (XVID).")
            self.video_writer = None
            self.recording = False
            return

        self.recording = True
        print(f"[VIDEO] start {self.video_path}")

    def write_frame(self, frame_bgr):
        if not self.recording or self.video_writer is None:
            return
        self.video_writer.write(frame_bgr)

    def stop_video(self):
        if self.video_writer is not None:
            self.video_writer.release()
            self.video_writer = None
        self.recording = False
        print("[VIDEO] stop")

    # DB – sesja

    def _db_insert_session(self, session_id: str, started_dt: datetime.datetime, aborted: bool):
        if not self.db_conn_str:
            return
        try:
            with psycopg2.connect(self.db_conn_str, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO public.sessions (session_id, started_utc, aborted) VALUES (%s, %s, %s)",
                        (session_id, started_dt, aborted)
                    )
                conn.commit()
        except Exception as e:
            print("[DB] INSERT sessions failed:", e)

    def _db_update_session_end(self, session_id: str, ended_dt: datetime.datetime, aborted: bool):
        if not self.db_conn_str:
            return
        try:
            with psycopg2.connect(self.db_conn_str, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE public.sessions SET ended_utc = %s, aborted = %s WHERE session_id = %s",
                        (ended_dt, aborted, session_id)
                    )
                conn.commit()
        except Exception as e:
            print("[DB] UPDATE sessions failed:", e)
