"""Single-flight background evaluation; no overlapping engine mutations."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty, Full


class PollRunner:
    def __init__(self, engine_factory):
        self._factory = engine_factory
        self._engine = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bstock-market")
        self.future = None
        self.closed = False
        self.close_future = None
        self._commands = Queue(maxsize=8)

    def _evaluate(self):
        if self._engine is None:
            self._engine = self._factory()
        while True:
            try:
                command = self._commands.get_nowait()
            except Empty:
                break
            self._engine.paper_control(command)
        return self._engine.evaluate_once()

    def command(self, action):
        if self.closed or action not in ("pause", "resume"):
            return False
        try:
            self._commands.put_nowait(action)
            return True
        except Full:
            return False

    def submit(self):
        if self.closed or self.future is not None:
            return False
        self.future = self._pool.submit(self._evaluate)
        return True

    def take(self):
        if self.future is None or not self.future.done():
            return None
        future, self.future = self.future, None
        return future  # result/exception handled by the GUI thread

    def close(self):
        if self.closed:
            return
        self.closed = True
        def dispose():
            close = getattr(self._engine, "close", None)
            if close is not None:
                close()
        self.close_future = self._pool.submit(dispose)
        self._pool.shutdown(wait=False, cancel_futures=False)
