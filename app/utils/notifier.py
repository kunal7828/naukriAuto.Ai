"""Best-effort email notifications via SMTP.

All functions swallow exceptions — a notification failure must never break
the bot.  When SMTP settings are missing, notifications are silently
skipped.
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any


def _smtp_config() -> dict[str, Any]:
    from app.config.config import settings

    return {
        "host": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
        "username": settings.SMTP_USERNAME,
        "password": settings.SMTP_PASSWORD,
        "from_addr": settings.SMTP_FROM,
        "to_addr": settings.SMTP_TO,
    }


def _is_configured() -> bool:
    cfg = _smtp_config()
    return bool(cfg["host"] and cfg["from_addr"] and cfg["to_addr"])


def send_notification(
    subject: str,
    body: str,
    html: str | None = None,
) -> bool:
    """Send an email notification. Returns True if sent, False otherwise."""
    if not _is_configured():
        return False
    cfg = _smtp_config()
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = cfg["from_addr"]
        msg["To"] = cfg["to_addr"]
        part1 = MIMEText(body, "plain", "utf-8")
        msg.attach(part1)
        if html:
            part2 = MIMEText(html, "html", "utf-8")
            msg.attach(part2)

        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
            try:
                server.starttls()
            except smtplib.SMTPException:
                pass
            if cfg["username"] and cfg["password"]:
                server.login(cfg["username"], cfg["password"])
            server.sendmail(cfg["from_addr"], [cfg["to_addr"]], msg.as_string())
        return True
    except Exception:
        return False


def notify_run_summary(
    total_applied: int,
    total_failed: int,
    questions_answered: int,
    report_paths: list[str] | None = None,
) -> bool:
    """Send a run summary email."""
    lines = [
        "Naukri AutoAI Run Summary",
        "=" * 30,
        f"Jobs Applied: {total_applied}",
        f"Jobs Failed/Skipped: {total_failed}",
        f"Questions Answered: {questions_answered}",
    ]
    if report_paths:
        lines.append("Reports:")
        for p in report_paths:
            lines.append(f"  - {p}")
    body = "\n".join(lines)
    return send_notification("Naukri AutoAI Run Complete", body)