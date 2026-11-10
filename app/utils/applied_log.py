"""Crash-safe log of confirmed job applications.

Reports are only written at the end of a session, so a hard kill (power loss,
`kill`, unhandled crash) used to lose the day's count and let the next run
overshoot the daily limit. This module appends one JSON record per line to
``data/applied_log.jsonl`` immediately after each batch, so the count survives
any crash. ``bot_runner._load_prior_applications()`` reads it together with
the reports.
"""
import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_PATH = os.path.join(BASE_DIR, "data", "applied_log.jsonl")


def append_applied(jobs: list[dict], status: str = "confirmed") -> None:
    """Append applications to the durable log. Safe to call often."""
    if not jobs:
        return
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        for job in jobs:
            url = (job.get("url") or "").strip()
            if not url:
                continue
            record = {
                "url": url,
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "applied_at": timestamp,
                "status": status,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_applied_log() -> list[dict]:
    """Read the durable log, tolerating a missing/corrupt file."""
    records = []
    if not os.path.exists(LOG_PATH):
        return records
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records
