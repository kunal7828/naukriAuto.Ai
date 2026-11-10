"""Single-instance OS-level file lock to prevent concurrent runs."""
import os
import sys
import errno
import subprocess


def _pid_alive(pid: int) -> bool:
    """Best-effort check whether a Windows process is still running."""
    if not pid or pid <= 0:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        return str(pid) in out
    except Exception:
        # If we cannot tell, assume the process is gone so we do not deadlock.
        return False


def _read_lock_pid(lock_path: str) -> int | None:
    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return None


class SingleInstanceLock:
    """Acquire an OS-level lock via a lock file.

    Uses ``open`` with ``O_CREAT | O_EXCL`` semantics on POSIX and a
    non-blocking lock on Windows so that only one bot instance can run
    at a time. Stale locks left behind by a crashed process are detected
    (via the recorded PID) and cleared automatically.

    Call ``acquire()`` at startup and ``release()`` on exit (or use the
    context manager).
    """

    def __init__(self, lock_path: str = "naukri_autoai.lock") -> None:
        self.lock_path = lock_path
        self._lock_fd = None
        self._acquired = False

    def acquire(self) -> bool:
        """Try to acquire the lock. Returns True on success."""
        if self._acquired:
            return True
        while True:
            try:
                # Create exclusively; fails if file already exists.
                fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_EXCL, 0o644)
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise
                # Lock exists: clear it if the owning process is gone.
                pid = _read_lock_pid(self.lock_path)
                if pid is not None and not _pid_alive(pid):
                    try:
                        os.unlink(self.lock_path)
                        print(
                            f"⚠️ Naukri AutoAI: Removed stale lock from dead process {pid}."
                        )
                        continue
                    except OSError:
                        pass
                return False
            try:
                os.write(fd, str(os.getpid()).encode())
            except Exception:
                pass
            self._lock_fd = fd
            self._acquired = True
            return True

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            if self._lock_fd is not None:
                os.close(self._lock_fd)
        except Exception:
            pass
        try:
            os.unlink(self.lock_path)
        except FileNotFoundError:
            pass
        self._acquired = False
        self._lock_fd = None

    def __enter__(self) -> "SingleInstanceLock":
        if not self.acquire():
            raise RuntimeError(
                f"Another Naukri AutoAI instance is already running "
                f"(lock file: {self.lock_path})."
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


def acquire_lock_or_exit(lock_path: str = "naukri_autoai.lock") -> SingleInstanceLock:
    """Acquire the lock or print an error and exit."""
    lock = SingleInstanceLock(lock_path)
    if not lock.acquire():
        print(
            "❌ Naukri AutoAI: Another instance is already running "
            f"(lock: {lock_path}). Exiting."
        )
        sys.exit(1)
    return lock
