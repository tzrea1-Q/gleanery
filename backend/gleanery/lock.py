import errno
import json
import os
import sys
import time
from pathlib import Path
from typing import IO, Any

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class InstanceLock:
    def __init__(self, data_dir: Path) -> None:
        descriptor = os.open(
            data_dir / "gleanery.lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        if sys.platform != "win32":
            os.fchmod(descriptor, 0o600)
        self.file: IO[str] = os.fdopen(descriptor, "r+", encoding="utf-8")
        self.acquired = False

    def acquire(self, port: int, token: str) -> bool:
        try:
            if sys.platform == "win32":
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            return False
        self.acquired = True
        self.file.seek(0)
        self.file.truncate()
        json.dump({"pid": os.getpid(), "port": port, "token": token}, self.file)
        self.file.flush()
        return True

    def read(self) -> dict[str, Any]:
        for attempt in range(100):
            self.file.seek(0)
            try:
                return json.load(self.file)
            except json.JSONDecodeError:
                if attempt == 99:
                    raise
                time.sleep(0.01)
        raise RuntimeError("无法读取实例信息")

    def close(self) -> None:
        if self.acquired:
            if sys.platform == "win32":
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()
