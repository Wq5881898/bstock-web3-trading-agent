"""Cancelable single-flight worker for desktop MCP account reads."""
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Full, Queue
from threading import Event


class McpAccountRunner:
    def __init__(self, reader):
        self._reader = reader
        self._pool = ThreadPoolExecutor(max_workers=1,
                                        thread_name_prefix="bstock-mcp-read")
        self._cancel = Event()
        self._urls = Queue(maxsize=1)
        self.future = None
        self.closed = False

    def _announce(self, url):
        try:
            self._urls.put_nowait(url)
        except Full:
            pass

    def _read(self, symbol):
        return self._reader(symbol, announce_url=self._announce,
                            cancelled=self._cancel.is_set)

    def start(self, symbol):
        if self.closed or self.future is not None:
            return False
        self._cancel.clear()
        while not self._urls.empty():
            self._urls.get_nowait()
        self.future = self._pool.submit(self._read, symbol)
        return True

    def take_url(self):
        try:
            return self._urls.get_nowait()
        except Empty:
            return None

    def take(self):
        if self.future is None or not self.future.done():
            return None
        future, self.future = self.future, None
        return future

    def cancel(self):
        self._cancel.set()

    def close(self):
        if self.closed:
            return
        if self.future is not None:
            raise RuntimeError("Cannot close a running MCP account reader")
        self.closed = True
        self._cancel.set()
        self._pool.shutdown(wait=True, cancel_futures=False)
