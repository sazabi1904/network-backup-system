"""Serialize writes to the same SSH endpoint within this Python process."""
from contextlib import contextmanager
from threading import Lock, RLock

_guard = Lock()
_locks = {}


@contextmanager
def device_operation(device):
    key = (device.info.host, device.info.port)
    with _guard:
        lock = _locks.setdefault(key, RLock())
    if not lock.acquire(blocking=False):
        raise RuntimeError('Another write operation is active for this SSH endpoint')
    try:
        yield
    finally:
        lock.release()
