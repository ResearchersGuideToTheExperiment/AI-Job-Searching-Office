import threading
import time
from office.config import DATA


class SharedInferenceLock:
    def __init__(self):
        self.thread_lock = threading.Lock()
        self.handle = None

    def __enter__(self):
        import msvcrt
        self.thread_lock.acquire()
        try:
            DATA.mkdir(parents=True, exist_ok=True)
            self.handle = (DATA/'inference.lock').open('a+b')
            # Windows byte-range locks may cover an empty file. Do not read
            # another worker's locked byte before attempting the lock.
            started = time.monotonic()
            while True:
                self.handle.seek(0)
                try:
                    msvcrt.locking(self.handle.fileno(),msvcrt.LK_NBLCK,1)
                    return self
                except OSError:
                    if time.monotonic()-started > 1800:
                        raise RuntimeError('Local AI is busy. Retry after the current operation finishes.')
                    time.sleep(.5)
        except Exception:
            if self.handle:
                self.handle.close()
            self.thread_lock.release()
            raise

    def __exit__(self,*args):
        import msvcrt
        try:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(),msvcrt.LK_UNLCK,1)
            self.handle.close()
        finally:
            self.handle.close()
            self.thread_lock.release()
