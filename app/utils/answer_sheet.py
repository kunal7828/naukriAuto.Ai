"""Curated Q&A sheet for recruiter questionnaire answers.

The bot logs every recruiter question it answers into
``data/reports/*.json``.  This module turns that history into an editable
spreadsheet (``data/resume/Question_Answers.xlsx``) so you can review and
correct answers, and it lets the bot prefer YOUR corrected answer over the
AI-generated one.

Sheet layout (sheet "Q&A Log"):
    # | Question | Options Seen | Answer Given | Times Asked | Last Asked |
    Source | Your Answer | Notes

- "Answer Given"  = what the bot actually submitted on Naukri.
- "Your Answer"   = EDIT THIS COLUMN. Anything you write here overrides the
                    AI answer for that exact question on future runs.
- "Notes"         = free-form notes for yourself.

If "Your Answer" is left blank, the bot falls back to its normal logic
(previous-answer cache, then AI).
"""
import json
import os
import re
from collections import defaultdict
from datetime import datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.utils.process_question import normalize

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORTS_DIR = os.path.join(BASE_DIR, "data", "reports")
RESUME_DIR = os.path.join(BASE_DIR, "data", "resume")
SHEET_PATH = os.path.join(RESUME_DIR, "Question_Answers.xlsx")

QUESTION_COL = "Question"
ANSWER_COL = "Your Answer"
COLS = ["#", QUESTION_COL, "Options Seen", "Answer Given", "Times Asked",
        "Last Asked", "Source", ANSWER_COL, "Notes"]


def _read_report_questions(path: str):
    """Yield (question, options, answer, timestamp, source_name) from a report."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return

    source = os.path.basename(path)
    stamp = str(data.get("generated_at", ""))

    for qa in data.get("questions_answered", []) or []:
        q = (qa.get("question") or "").strip()
        if not q:
            continue
        yield (
            q,
            qa.get("options") or "",
            qa.get("answer") or "",
            stamp,
            source,
        )


def collect_history():
    """Aggregate every answered question across all reports (raw + daily)."""
    history = {}
    order = []

    files = []
    if os.path.isdir(REPORTS_DIR):
        files = [os.path.join(REPORTS_DIR, f) for f in os.listdir(REPORTS_DIR)
                 if f.endswith(".json")]
    daily_dir = os.path.join(REPORTS_DIR, "daily")
    if os.path.isdir(daily_dir):
        files += [os.path.join(daily_dir, f) for f in os.listdir(daily_dir)
                  if f.endswith(".json")]

    for path in sorted(files):
        for q, opts, ans, stamp, source in _read_report_questions(path):
            key = normalize(q)
            if not key:
                continue
            if key not in history:
                history[key] = {
                    "question": q,
                    "options": opts,
                    "answers": [],
                    "count": 0,
                    "last_asked": "",
                    "sources": set(),
                }
                order.append(key)
            entry = history[key]
            entry["count"] += 1
            entry["answers"].append(ans)
            if stamp > entry["last_asked"]:
                entry["last_asked"] = stamp
            entry["sources"].add(source)

    for key in order:
        entry = history[key]
        entry["answers"] = [a for a in entry["answers"] if a]
        entry["answer_given"] = entry["answers"][-1] if entry["answers"] else ""
        entry["sources"] = sorted(entry["sources"])

    return [history[k] for k in order]


def load_curated_answers(path: str | None = None) -> dict:
    """Return {normalized_question: your_answer} from the sheet.

    Only rows where you actually wrote an answer are returned.
    """
    path = path or SHEET_PATH
    if not os.path.exists(path):
        return {}

    curated = {}
    try:
        wb = load_workbook(path, data_only=True)
        ws = wb["Q&A Log"] if "Q&A Log" in wb.sheetnames else wb.active
    except Exception:
        return {}

    headers = {}
    for cell in ws[1]:
        if cell.value:
            headers[str(cell.value).strip()] = cell.column

    q_col = headers.get(QUESTION_COL)
    a_col = headers.get(ANSWER_COL)
    if not q_col or not a_col:
        return {}

    for row in ws.iter_rows(min_row=2, values_only=True):
        q = row[q_col - 1] if q_col - 1 < len(row) else None
        a = row[a_col - 1] if a_col - 1 < len(row) else None
        if not q or not a:
            continue
        q = str(q).strip()
        a = str(a).strip()
        if not q or not a or a.lower() in ("not specified", "n/a", "-"):
            continue
        curated[normalize(q)] = a

    return curated


def find_curated_answer(question: str, curated: dict | None = None) -> str | None:
    """Return your curated answer for this question, if you provided one."""
    if curated is None:
        curated = load_curated_answers()
    if not curated:
        return None
    return curated.get(normalize(question))


def refresh_answer_sheet(path: str | None = None) -> str:
    """Rebuild the Q&A sheet from report history, preserving your edits."""
    path = path or SHEET_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)

    history = collect_history()
    existing = load_curated_answers(path)

    wb = Workbook()
    ws = wb.active
    ws.title = "Q&A Log"

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(bold=True, color="FFFFFF")
    edit_fill = PatternFill("solid", fgColor="FFF2CC")

    for c, title in enumerate(COLS, start=1):
        cell = ws.cell(row=1, column=c, value=title)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for i, entry in enumerate(history, start=1):
        row = [
            i,
            entry["question"],
            entry["options"],
            entry["answer_given"],
            entry["count"],
            entry["last_asked"],
            ", ".join(entry["sources"]),
            existing.get(normalize(entry["question"]), ""),
            "",
        ]
        for c, value in enumerate(row, start=1):
            cell = ws.cell(row=i + 1, column=c, value=value)
            cell.alignment = Alignment(vertical="top", wrap_text=(c in (2, 3, 4, 8, 9)))
        # Highlight the editable column.
        ws.cell(row=i + 1, column=COLS.index(ANSWER_COL) + 1).fill = edit_fill

    widths = [5, 55, 30, 35, 11, 20, 32, 35, 25]
    for c, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A2"

    # Second sheet: profile details from the ODS, for quick reference.
    try:
        _write_profile_sheet(wb)
    except Exception:
        pass

    wb.save(path)
    return path


def _write_profile_sheet(wb: Workbook) -> None:
    """Dump the ODS profile into a readable sheet (best effort)."""
    import zipfile
    import xml.etree.ElementTree as ET

    ods_path = os.path.join(RESUME_DIR, "Kunal_Information_Organized.ods")
    if not os.path.exists(ods_path):
        return

    NS = {"table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0"}
    with zipfile.ZipFile(ods_path) as z:
        root = ET.fromstring(z.read("content.xml"))

    rows = []
    for tbl in root.iter("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table"):
        for tr in tbl.iter("{urn:oasis:names:tc:opendocument:xmlns:table:1.0}table-row"):
            cells = []
            for tc in tr.findall("table:table-cell", NS):
                rep = int(tc.get(
                    "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
                    "number-columns-repeated", "1"))
                txt = "".join(tc.itertext()).strip()
                rep = 1 if rep > 50 else rep
                cells.extend([txt] * rep)
            while cells and cells[-1] == "":
                cells.pop()
            if cells:
                rows.append(cells)

    ws = wb.create_sheet("Profile (ODS)")
    ws.append(["Field", "Value"])
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="1F4E78")
        c.font = Font(bold=True, color="FFFFFF")
    for r in rows:
        ws.append(r[:2] if len(r) >= 2 else (r + [""])[:2])
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 60


if __name__ == "__main__":
    out = refresh_answer_sheet()
    print(f"Q&A sheet written: {out}")
    print(f"Curated answers: {len(load_curated_answers(out))}")
