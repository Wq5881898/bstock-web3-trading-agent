"""Short-lived loopback listener. No browser, Binance requests or credential files."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from queue import Queue, Empty
from threading import Thread

from bstock_web3.oauth_flow import AuthorizationAttempt


class CallbackListener:
    """Use as a context manager; close after receiving the sensitive token form."""

    def __init__(self, client_id,
                 callback_path="/callback/bstock-web3-trading-agent"):
        self._results = Queue(maxsize=1)
        self._closed = False
        self._completed = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # callback paths contain authorization codes

            def setup(self):
                self.request.settimeout(2)
                super().setup()

            def do_GET(self):
                if owner._completed:
                    self.reply(410, b"Authorization attempt already completed.")
                    return
                if self.headers.get("Host") != owner._authority or not self.path.startswith("/callback/"):
                    self.reply(400, b"Invalid callback.")
                    return
                try:
                    form = owner.attempt.consume_callback("http://" + owner._authority + self.path)
                except ValueError:
                    self.reply(400, b"Authorization callback rejected. Restart login if expired or denied.")
                    return
                owner._completed = True
                owner._results.put_nowait(form)
                self.reply(200, b"Callback received. Return to the application to finish authentication.")

            def reply(self, status, body):
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._authority = f"127.0.0.1:{self._server.server_port}"
        try:
            self.attempt = AuthorizationAttempt(
                client_id, f"http://{self._authority}{callback_path}")
        except Exception:
            self._server.server_close()
            raise
        self._thread = Thread(target=self._server.serve_forever, kwargs={"poll_interval": .1}, daemon=True)
        self._thread.start()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def receive(self, timeout=1):
        if self._closed:
            raise ValueError("Callback listener is closed")
        if not 0 <= timeout <= 5:
            raise ValueError("Poll timeout must be between 0 and 5 seconds")
        try:
            return self._results.get(timeout=timeout)
        except Empty:
            return None

    def close(self):
        if not self._closed:
            self._closed = True
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=3)
            while not self._results.empty():
                self._results.get_nowait()
