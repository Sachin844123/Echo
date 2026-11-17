"""OS-released lock prevents two workers recovering the same queue."""

import os
from pathlib import Path


class InstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def acquire(self) -> None:
        stream = self.path.open("a+b")
        try:
            if stream.seek(0, 2) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise RuntimeError("another ECHO instance is using this data directory") from None
        self.stream = stream

    def release(self) -> None:
        if self.stream is not None:
            self.stream.close()
            self.stream = None
