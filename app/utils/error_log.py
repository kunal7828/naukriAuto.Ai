import json
import os
from datetime import datetime


def log_error(step: str, exc: Exception, url: str = "") -> str:
    issue_id = f"ERR-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    entry = {
        "issue_id": issue_id,
        "timestamp": datetime.now().isoformat(),
        "step": step,
        "exception": type(exc).__name__,
        "message": str(exc)[:500],
        "url": url,
    }
    os.makedirs("data", exist_ok=True)
    with open("data/error_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return issue_id
