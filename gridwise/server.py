"""Small threaded JSON service. Use a reverse proxy with request deadlines in deployment."""
import json
import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .llm import Interpreter
from .optimizer import optimize
from .validation import load_json, validate_request, Invalid

EXECUTOR = ThreadPoolExecutor(max_workers=4)
SLOTS = threading.BoundedSemaphore(4)


def make_handler(interpreter):
    def process(data):
        try:
            directives = interpreter.interpret(data)
            return optimize(data, directives)
        finally:
            SLOTS.release()

    class Handler(BaseHTTPRequestHandler):
        server_version = "GridWise"

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass  # Avoid logging arbitrary URL or user/provider content.

        def send_json(self, status, value):
            body = json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                pass

        def do_GET(self):
            if self.path == "/health":
                self.send_json(200, {"status": "ok"})
            else:
                self.send_json(404, {"error": "Not found"})

        def do_POST(self):
            if self.path != "/optimize-energy":
                self.send_json(404, {"error": "Not found"})
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise Invalid("Unsupported transfer encoding")
                if self.headers.get_content_type() != "application/json":
                    raise Invalid("Expected application/json")
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1:
                    raise Invalid("Expected content length")
                length = int(lengths[0])
                if not 0 < length <= 1048576:
                    raise Invalid("Invalid request size")
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise Invalid("Incomplete body")
                data = validate_request(load_json(raw))
            except (ValueError, TypeError, OverflowError, socket.timeout):
                self.send_json(400, {"error": "Malformed JSON or invalid scenario"})
                return
            if not SLOTS.acquire(blocking=False):
                self.send_json(500, {"error": "Service busy; retry later"})
                return
            future = EXECUTOR.submit(process, data)
            try:
                output = future.result(timeout=25)
                self.send_json(200, output)
            except TimeoutError:
                # Work keeps its slot until finished; avoids unbounded orphan jobs.
                self.send_json(500, {"error": "Processing deadline exceeded"})
            except Exception:
                self.send_json(500, {"error": "Could not produce a verified energy plan"})

    return Handler


def main():
    try:
        interpreter = Interpreter()
        port = int(os.environ.get("PORT", "8000"))
    except Exception:
        raise SystemExit("Startup failed: check documented environment configuration.")
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(interpreter))
    print("GridWise HTTP service ready", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
