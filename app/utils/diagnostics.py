"""Per-run diagnostics: logging, screenshots, and run metadata."""
import json
import os
import sys
import traceback
from datetime import datetime
from typing import Any


class Diagnostics:
    """Collects per-run diagnostic information and writes it to disk."""

    def __init__(self, diagnostics_dir: str = "data/diagnostics") -> None:
        self.diagnostics_dir = diagnostics_dir
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = os.path.join(diagnostics_dir, self.run_id)
        self.log_lines: list[str] = []
        self.errors: list[dict[str, Any]] = []
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        os.makedirs(self.run_dir, exist_ok=True)

    def log(self, message: str) -> None:
        """Log a message both to stdout and to the in-memory log."""
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        self.log_lines.append(line)
        print(message, flush=True)

    def record_error(
        self,
        step: str,
        exc: Exception,
        url: str = "",
        screenshot_path: str | None = None,
    ) -> str:
        """Record an error with full context. Returns an issue ID."""
        issue_id = f"ERR-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        entry = {
            "issue_id": issue_id,
            "timestamp": datetime.now().isoformat(),
            "step": step,
            "exception_type": type(exc).__name__,
            "message": str(exc)[:500],
            "traceback": traceback.format_exc(),
            "url": url,
            "screenshot": screenshot_path,
        }
        self.errors.append(entry)
        return issue_id

    async def take_screenshot(self, page: Any, name: str = "screenshot") -> str | None:
        """Take a full-page screenshot and return the saved path."""
        if page is None:
            return None
        try:
            path = os.path.join(self.run_dir, f"{name}.png")
            await page.screenshot(path=path, full_page=True)
            return path
        except Exception:
            return None

    def save(self) -> str:
        """Write the run diagnostics to disk and return the path."""
        payload = {
            "run_id": self.run_id,
            "started_at": self.run_id,
            "errors": self.errors,
            "log": self.log_lines,
        }
        path = os.path.join(self.run_dir, "run_diagnostics.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        return path


# Module-level helper to set up logging to a file as well as stdout
def setup_file_logging(diagnostics_dir: str = "data/diagnostics") -> tuple[str, Any]:
    """Configure a per-run log file and return (log_path, diagnostics)."""
    os.makedirs(diagnostics_dir, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(diagnostics_dir, f"run_{run_id}.log")

    diagnostics = Diagnostics(diagnostics_dir)

    # Tee stdout so prints also go to the log file
    class _Tee:
        def __init__(self, *streams):
            self.streams = streams

        def write(self, data):
            for s in self.streams:
                try:
                    s.write(data)
                except Exception:
                    pass

        def flush(self):
            for s in self.streams:
                try:
                    s.flush()
                except Exception:
                    pass

    try:
        log_fp = open(log_path, "a", encoding="utf-8")
        sys.stdout = _Tee(sys.__stdout__, log_fp)
        sys.stderr = _Tee(sys.__stderr__, log_fp)
    except Exception:
        log_fp = None

    return log_path, diagnostics