"""OS-released per-database process lock. Never unlink a lockfile while held."""

import os


class InstanceLock:
    def __init__(self, path):
        self.stream = open(path, "a+b")
        self.held = False

    def acquire(self):
        self.stream.seek(0)
        if os.name == "nt":
            import msvcrt

            # Windows byte-range locks also deny reads by other processes.
            # Lock directly, including on an empty file; do not read the held byte.
            try:
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return False
        else:
            import fcntl

            try:
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
        self.held = True
        return True

    def close(self):
        if self.held:
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        self.stream.close()
        self.held = False
