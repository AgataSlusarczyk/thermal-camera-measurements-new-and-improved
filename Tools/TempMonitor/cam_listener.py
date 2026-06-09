import json
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone


def _get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CamListener:
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
            print(f"[CamListener] nasłuchuję na http://{self.host}:{self.port}/ping")

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server = None
        if self.verbose:
            print("[CamListener] zatrzymany")

    def _handle_ping(self, handler):
        rec = self.recorder

        if not rec.measuring:
            handler._reply(409, "No active session")
            if self.verbose:
                print("[CamListener] ping odrzucony – brak aktywnej sesji")
            return

        # Odczytaj JSON z body – wymagany
        try:
            length = int(handler.headers.get("Content-Length", 0))
            body = handler.rfile.read(length)
            data = json.loads(body)
            scenario = data["scenario"]
            duration = data["duration"]
        except Exception as e:
            handler._reply(400, f"Bad request: {e}")
            if self.verbose:
                print(f"[CamListener] ping odrzucony – zły JSON: {e}")
            return

        # Inkrementuj flag_id
        rec.flag_id += 1
        new_flag = rec.flag_id

        # Timestamp
        utc_now = _get_utc_now()
        t_s = f"{time.monotonic() - rec.t0_mono:.3f}".replace('.', ',')

        # Zapis do CSV
        rec.csv_wr.writerow([
            utc_now.isoformat() + "Z",
            t_s,
            "",        # temp_roi1
            "",        # temp_roi2
            "",        # temp_roi3
            new_flag,
            scenario,
            duration,
        ])
        rec.csv_fh.flush()
        if rec.session_id is not None and rec._dbw is not None:
            rec._dbw.enqueue(
                rec.session_id,
                utc_now.replace(tzinfo=None),  # psycopg2 lubi naive datetime
                float(t_s.replace(',', '.')),
                None, None, None,  # temps puste
                new_flag,
            )

        if self.verbose:
            print(f"[CamListener] PING @ t={t_s}s | flag_id={new_flag} | scenario={scenario} duration={duration}")

        handler._reply(200, f"flag_id={new_flag}")