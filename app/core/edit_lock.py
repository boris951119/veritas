"""同一产物目录的人工改写互斥。

同进程串行，避免两笔修改交错写坏 report.json / chain.jsonl。
跨进程再用文件锁。版本是否过期由调用方用账本条数核对。
"""

from __future__ import annotations

import sys
import threading
from contextlib import contextmanager
from pathlib import Path

_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


@contextmanager
def out_edit_lock(out_dir: Path):
    key = str(Path(out_dir).resolve())
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        path = Path(out_dir) / ".edit.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(path, "a+", encoding="utf-8")
        try:
            if sys.platform == "win32":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            fh.close()
