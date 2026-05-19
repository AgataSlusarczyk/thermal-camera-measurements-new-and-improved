import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone


def _get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PingListener:
    def __init__(self, recorder, port: int = 5050, host: str = "0.0.0.0", verbose: bool = True):
        self.recorder = recorder
        self.port = port
        self.host = host
        self.verbose = verbose
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self):
        listener = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path == "/ping":
                    listener._handle_ping(self)
                else:
                    self._reply(404, "Not Found")

            def do_GET(self):
                if self.path in ("/health", "/"):
                    self._reply(200, "OK")
                else:
                    self._reply(404, "Not Found")

            def _reply(self, code: int, body: str):
                encoded = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, fmt, *args):
                if listener.verbose:
                    print(f"[HTTP] {self.address_string()} – {fmt % args}")

        self._server = HTTPServer((self.host, self.port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        if self.verbose:
            print(f"[PingListener] nasłuchuję na http://{self.host}:{self.port}/ping")

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server = None
        if self.verbose:
            print("[PingListener] zatrzymany")

    def _handle_ping(self, handler):
        rec = self.recorder

        if not rec.measuring:
            handler._reply(409, "No active session")
            if self.verbose:
                print("[PingListener] ping odrzucony – brak aktywnej sesji")
            return

        # 1. Inkrementuj flag_id (int, start od 1)
        rec.flag_id += 1
        new_flag = rec.flag_id

        # 2. Timestamp zdarzenia
        utc_now = _get_utc_now()
        t_s = f"{time.monotonic() - rec.t0_mono:.3f}".replace('.', ',')

        # 3. Wiersz-marker w CSV: temp_roi* puste (to znacznik, nie pomiar temperatury)
        rec.csv_wr.writerow([
            utc_now.isoformat() + "Z",  # timestamp
            t_s,
            "",
            "",
            "",
            new_flag,
        ])
        rec.csv_fh.flush()

        if self.verbose:
            print(f"[PingListener] PING @ t={t_s}s | flag_id -> {new_flag}")

        handler._reply(200, f"flag_id={new_flag}")