"""Build per-day application reports and a self-contained HTML dashboard.

Raw per-run reports live in ``data/reports/*.json``. This module merges them
into one report per calendar day (``data/reports/daily/YYYY-MM-DD.json``) and
renders ``data/reports/dashboard.html`` with the data embedded, so the
dashboard works offline by simply double-clicking it.

Run manually with::

    python -m app.utils.daily_report
"""
import json
import os
import re
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOURCE_DIR = os.path.join(PROJECT_ROOT, "data", "reports")
DAILY_DIR = os.path.join(SOURCE_DIR, "daily")
DASHBOARD_PATH = os.path.join(SOURCE_DIR, "dashboard.html")

_DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _job_key(job: dict) -> str:
    url = (job.get("url") or "").strip()
    if url:
        return url
    return f"{(job.get('title') or '').strip().lower()}|{(job.get('company') or '').strip().lower()}"


def _report_day(data: dict) -> str:
    match = _DATE_PATTERN.search(str(data.get("generated_at", "")))
    return match.group(1) if match else datetime.now().strftime("%Y-%m-%d")


def _item_day(item: dict, fallback: str) -> str:
    stamp = str(item.get("applied_at") or item.get("attempted_at") or "")
    match = _DATE_PATTERN.search(stamp)
    return match.group(1) if match else fallback


def _clean_job(job: dict) -> dict:
    return {
        "title": job.get("title") or "Unknown role",
        "company": job.get("company") or "Unknown company",
        "url": job.get("url") or "",
        "applied_at": job.get("applied_at") or job.get("attempted_at") or "",
    }


def _company_breakdown(jobs: list[dict]) -> list[dict]:
    companies: dict[str, dict] = {}
    for job in jobs:
        name = (job.get("company") or "Unknown company").strip() or "Unknown company"
        entry = companies.setdefault(name, {"name": name, "count": 0, "roles": [], "jobs": []})
        entry["count"] += 1
        title = job.get("title") or "Unknown role"
        if title not in entry["roles"]:
            entry["roles"].append(title)
        entry["jobs"].append(job)
    return sorted(companies.values(), key=lambda c: (-c["count"], c["name"].lower()))


def load_days() -> dict:
    """Merge every raw run report into day buckets."""
    if not os.path.isdir(SOURCE_DIR):
        return {}

    jobs_by_day: dict[str, dict[str, dict]] = {}
    questions_by_day: dict[str, dict[str, dict]] = {}
    failed_by_day: dict[str, dict[str, dict]] = {}

    for fname in sorted(os.listdir(SOURCE_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(SOURCE_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        fallback = _report_day(data)

        for job in data.get("jobs", []):
            day = _item_day(job, fallback)
            jobs_by_day.setdefault(day, {})[_job_key(job)] = _clean_job(job)

        for qa in data.get("questions_answered", []):
            question = (qa.get("question") or "").strip()
            if not question:
                continue
            key = question.lower()
            questions_by_day.setdefault(fallback, {}).setdefault(key, qa)

        for job in data.get("failed_jobs", []):
            day = _item_day(job, fallback)
            failed_by_day.setdefault(day, {})[_job_key(job)] = {
                **job,
                "title": job.get("title") or "Unknown role",
                "company": job.get("company") or "Unknown company",
            }

    all_days = set(jobs_by_day) | set(questions_by_day) | set(failed_by_day)
    reports: dict[str, dict] = {}

    for day in all_days:
        jobs = sorted(
            jobs_by_day.get(day, {}).values(),
            key=lambda job: str(job.get("applied_at", "")),
        )
        companies = _company_breakdown(jobs)
        questions = list(questions_by_day.get(day, {}).values())
        failed = list(failed_by_day.get(day, {}).values())
        if not jobs and not questions and not failed:
            continue
        reports[day] = {
            "date": day,
            "total_applied": len(jobs),
            "total_companies": len(companies),
            "jobs": jobs,
            "companies": companies,
            "questions_answered": questions,
            "failed_jobs": failed,
        }

    return reports


def build_daily_reports() -> dict:
    """Write one merged JSON report per day and return the data."""
    reports = load_days()
    os.makedirs(DAILY_DIR, exist_ok=True)

    # Remove stale daily files so the folder always mirrors the source reports.
    for fname in os.listdir(DAILY_DIR):
        if fname.endswith(".json") and fname[:-5] not in reports:
            try:
                os.remove(os.path.join(DAILY_DIR, fname))
            except OSError:
                pass

    for day, report in reports.items():
        with open(os.path.join(DAILY_DIR, f"{day}.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

    return reports


def _dashboard_payload(reports: dict) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    dates = sorted(set(reports) | {today, yesterday}, reverse=True)

    all_companies = set()
    for report in reports.values():
        for company in report.get("companies", []):
            all_companies.add(company["name"])

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "today": today,
        "yesterday": yesterday,
        "dates": dates,
        "days": reports,
        "all_time": {
            "applications": sum(r.get("total_applied", 0) for r in reports.values()),
            "companies": len(all_companies),
            "days": len(reports),
        },
    }


def generate_dashboard(reports: dict | None = None) -> str:
    """Render the self-contained dashboard and return its path."""
    if reports is None:
        reports = build_daily_reports()

    payload = _dashboard_payload(reports)
    embedded = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = _TEMPLATE.replace("__DATA__", embedded)

    with open(DASHBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    return DASHBOARD_PATH


def refresh() -> tuple[str, str]:
    """Rebuild daily JSON files and the dashboard. Returns (daily_dir, dashboard)."""
    reports = build_daily_reports()
    path = generate_dashboard(reports)
    return DAILY_DIR, path


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Naukri AutoAI - Application Dashboard</title>
<style>
  :root{
    --bg:#f4f6fb; --panel:#ffffff; --ink:#17203a; --muted:#6b7694;
    --line:#e6e9f2; --accent:#4f46e5; --accent-soft:#eef0ff;
    --good:#0f9d76; --warn:#d97706; --bad:#dc2626;
    --shadow:0 10px 30px rgba(23,32,58,.08);
    --radius:16px;
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0}
  body{
    font-family:"Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif;
    background:var(--bg); color:var(--ink); -webkit-font-smoothing:antialiased;
  }
  a{color:inherit}
  .app{display:grid;grid-template-columns:290px minmax(0,1fr);min-height:100vh}

  /* Sidebar */
  .sidebar{
    position:sticky;top:0;height:100vh;overflow:auto;
    background:linear-gradient(180deg,#141a33 0%,#0f1428 100%);
    color:#e8ebff;padding:26px 18px;display:flex;flex-direction:column;gap:22px;
  }
  .brand{display:flex;align-items:center;gap:12px;padding:0 6px}
  .brand-mark{
    width:42px;height:42px;border-radius:13px;display:grid;place-items:center;
    background:linear-gradient(135deg,#6366f1,#a855f7);font-weight:800;font-size:18px;
    box-shadow:0 8px 20px rgba(99,102,241,.45);
  }
  .brand-title{font-size:16px;font-weight:700;line-height:1.2}
  .brand-sub{font-size:11px;color:#9aa3c7;letter-spacing:.4px;text-transform:uppercase}
  .side-label{
    font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#8f98bd;
    padding:0 8px;margin-bottom:8px;font-weight:700;
  }
  .date-list{display:flex;flex-direction:column;gap:6px}
  .date-btn{
    width:100%;display:flex;align-items:center;justify-content:space-between;gap:10px;
    background:transparent;border:1px solid transparent;color:#dfe4ff;
    padding:10px 12px;border-radius:12px;cursor:pointer;text-align:left;font:inherit;
    transition:background .15s,border-color .15s,transform .15s;
  }
  .date-btn:hover{background:rgba(255,255,255,.06)}
  .date-btn.active{background:rgba(99,102,241,.22);border-color:rgba(99,102,241,.55)}
  .date-btn .d-main{display:flex;flex-direction:column;gap:2px}
  .date-btn .d-rel{font-size:13px;font-weight:600}
  .date-btn .d-full{font-size:11px;color:#98a1c6}
  .date-btn .d-count{
    min-width:28px;height:24px;padding:0 8px;border-radius:999px;display:grid;place-items:center;
    background:rgba(255,255,255,.1);font-size:11px;font-weight:700;color:#fff;
  }
  .date-btn.active .d-count{background:#6366f1}
  .date-btn.empty .d-count{background:rgba(255,255,255,.06);color:#8f98bd}
  .side-foot{
    margin-top:auto;border-top:1px solid rgba(255,255,255,.1);padding:16px 8px 0;
    display:grid;gap:8px;font-size:12px;color:#98a1c6;
  }
  .side-foot b{color:#fff;font-size:16px;display:block}

  /* Main */
  main{padding:34px 38px 56px;max-width:1400px;width:100%}
  .top{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;flex-wrap:wrap;margin-bottom:26px}
  .page-title{margin:0;font-size:27px;letter-spacing:-.4px}
  .page-sub{margin:6px 0 0;color:var(--muted);font-size:13px}
  .top-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
  .pill{
    display:inline-flex;align-items:center;gap:8px;padding:8px 14px;border-radius:999px;
    background:var(--panel);border:1px solid var(--line);font-size:13px;font-weight:600;
    box-shadow:var(--shadow);
  }
  .pill .dot{width:8px;height:8px;border-radius:50%;background:var(--accent)}
  .btn-link{
    text-decoration:none;padding:9px 15px;border-radius:11px;background:var(--accent);color:#fff;
    font-size:13px;font-weight:600;box-shadow:0 8px 18px rgba(79,70,229,.28);
  }
  .btn-link.ghost{background:var(--panel);color:var(--accent);border:1px solid var(--line);box-shadow:none}

  .cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-bottom:22px}
  .card{
    background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
    padding:18px 20px;box-shadow:var(--shadow);position:relative;overflow:hidden;
  }
  .card::after{
    content:"";position:absolute;inset:auto -30px -40px auto;width:110px;height:110px;border-radius:50%;
    background:radial-gradient(circle,rgba(99,102,241,.16),transparent 70%);
  }
  .card .k{font-size:12px;color:var(--muted);font-weight:600;letter-spacing:.03em}
  .card .v{font-size:32px;font-weight:800;letter-spacing:-1px;margin-top:6px}
  .card .s{font-size:12px;color:var(--muted);margin-top:4px}

  .panel{
    background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
    box-shadow:var(--shadow);margin-bottom:22px;overflow:hidden;
  }
  .panel-head{
    display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;
    padding:18px 22px;border-bottom:1px solid var(--line);
  }
  .panel-head h2{margin:0;font-size:16px;letter-spacing:-.2px}
  .panel-head .hint{color:var(--muted);font-size:12px}
  .panel-body{padding:20px 22px}

  /* Chart */
  .chart{display:flex;align-items:flex-end;gap:10px;height:180px;padding:8px 2px 0}
  .bar-col{flex:1;min-width:0;display:flex;flex-direction:column;align-items:center;gap:8px;cursor:pointer}
  .bar-track{width:100%;height:132px;display:flex;align-items:flex-end;justify-content:center}
  .bar{
    width:min(42px,80%);min-height:4px;border-radius:9px 9px 4px 4px;
    background:linear-gradient(180deg,#818cf8,#4f46e5);transition:transform .15s,filter .15s;
    position:relative;
  }
  .bar-col:hover .bar{transform:translateY(-3px);filter:brightness(1.06)}
  .bar-col.selected .bar{background:linear-gradient(180deg,#a855f7,#7c3aed);box-shadow:0 0 0 3px rgba(124,58,237,.18)}
  .bar-val{font-size:11px;font-weight:700;color:var(--ink)}
  .bar-lbl{font-size:10px;color:var(--muted);white-space:nowrap}
  .bar-col.selected .bar-lbl{color:var(--accent);font-weight:700}
  .chart-empty{color:var(--muted);font-size:13px;padding:30px 0;text-align:center;width:100%}

  /* Companies */
  .company-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
  .company-card{
    border:1px solid var(--line);border-radius:13px;padding:14px 15px;cursor:pointer;
    background:#fbfcff;transition:border-color .15s,box-shadow .15s,transform .15s;
  }
  .company-card:hover{border-color:#c7ccf8;box-shadow:0 8px 20px rgba(79,70,229,.10);transform:translateY(-1px)}
  .company-card.active{border-color:var(--accent);box-shadow:0 0 0 3px rgba(79,70,229,.12);background:var(--accent-soft)}
  .company-top{display:flex;align-items:center;justify-content:space-between;gap:10px}
  .company-name{font-size:13.5px;font-weight:700;line-height:1.25}
  .company-count{
    flex:none;min-width:26px;height:24px;padding:0 8px;border-radius:999px;display:grid;place-items:center;
    background:var(--accent-soft);color:var(--accent);font-size:11px;font-weight:800;
  }
  .company-roles{margin:8px 0 0;padding:0;list-style:none;display:grid;gap:4px}
  .company-roles li{font-size:11.5px;color:var(--muted);line-height:1.35;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .company-roles li::before{content:"•";color:#c3c8e8;margin-right:6px}

  /* Search + table */
  .search{
    display:flex;align-items:center;gap:8px;background:#f7f8fd;border:1px solid var(--line);
    border-radius:11px;padding:8px 12px;min-width:240px;
  }
  .search input{border:0;background:transparent;outline:0;font:inherit;font-size:13px;color:var(--ink);width:100%}
  .search svg{flex:none}
  .table-wrap{overflow:auto;max-height:560px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  thead th{
    position:sticky;top:0;background:#fafbff;text-align:left;padding:12px 16px;
    font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);
    border-bottom:1px solid var(--line);z-index:1;
  }
  tbody td{padding:12px 16px;border-bottom:1px solid #f0f2f9;vertical-align:middle}
  tbody tr:hover{background:#fafbff}
  td.idx{color:#a3aac4;font-weight:600;width:52px}
  td.company{font-weight:600}
  td.role a{color:var(--accent);text-decoration:none;font-weight:600}
  td.role a:hover{text-decoration:underline}
  td.time{color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums;width:110px}
  .empty-state{padding:44px 20px;text-align:center;color:var(--muted)}
  .empty-state .big{font-size:30px;margin-bottom:8px}
  .filter-chip{
    display:none;align-items:center;gap:8px;background:var(--accent-soft);color:var(--accent);
    padding:6px 10px;border-radius:999px;font-size:12px;font-weight:700;
  }
  .filter-chip.show{display:inline-flex}
  .filter-chip button{
    border:0;background:transparent;color:inherit;cursor:pointer;font-size:14px;line-height:1;padding:0;
  }
  @media (max-width:1100px){
    .app{grid-template-columns:240px minmax(0,1fr)}
    .cards{grid-template-columns:repeat(2,minmax(0,1fr))}
    main{padding:26px 22px 44px}
  }
  @media (max-width:760px){
    .app{grid-template-columns:1fr}
    .sidebar{position:relative;height:auto}
    .date-list{flex-direction:row;overflow:auto;padding-bottom:4px}
    .date-btn{min-width:170px}
    .cards{grid-template-columns:1fr 1fr}
  }
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-mark">N</div>
      <div>
        <div class="brand-title">Naukri AutoAI</div>
        <div class="brand-sub">Application Dashboard</div>
      </div>
    </div>

    <div>
      <div class="side-label">Report days</div>
      <div class="date-list" id="dateList"></div>
    </div>

    <div class="side-foot">
      <div><b id="footTotal">0</b>total applications</div>
      <div><b id="footCompanies">0</b>companies reached</div>
      <div><b id="footDays">0</b>days tracked</div>
    </div>
  </aside>

  <main>
    <div class="top">
      <div>
        <h1 class="page-title">Application Dashboard</h1>
        <p class="page-sub" id="pageSub">Daily job applications and company details</p>
      </div>
      <div class="top-actions">
        <span class="pill"><span class="dot"></span><span id="selectedLabel">Today</span></span>
        <a class="btn-link ghost" id="downloadDay" href="#" download>Daily JSON</a>
      </div>
    </div>

    <section class="cards" id="summaryCards"></section>

    <section class="panel">
      <div class="panel-head">
        <h2>Applications by day</h2>
        <span class="hint">Click a bar to open that day</span>
      </div>
      <div class="panel-body">
        <div class="chart" id="chart"></div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>Companies applied</h2>
        <span class="hint" id="companyHint">Click a company to filter its jobs</span>
      </div>
      <div class="panel-body">
        <div class="company-grid" id="companyGrid"></div>
      </div>
    </section>

    <section class="panel" id="jobsPanel">
      <div class="panel-head">
        <h2>Applied jobs</h2>
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          <span class="filter-chip" id="filterChip">
            <span id="filterChipText"></span>
            <button type="button" id="clearFilter" aria-label="Clear filter">×</button>
          </span>
          <label class="search">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#8b93b2" stroke-width="2">
              <circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path>
            </svg>
            <input id="jobSearch" type="search" placeholder="Search company or role...">
          </label>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>#</th><th>Company</th><th>Role</th><th>Applied</th></tr>
          </thead>
          <tbody id="jobsBody"></tbody>
        </table>
        <div class="empty-state" id="jobsEmpty" style="display:none">
          <div class="big">🗂️</div>
          <div id="jobsEmptyText">No applications recorded for this day.</div>
        </div>
      </div>
    </section>
  </main>
</div>

<script>
const DATA = __DATA__;

const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[ch]));

const state = { date: null, company: null, query: "" };

function emptyDay(date) {
  return { date, total_applied: 0, total_companies: 0, jobs: [], companies: [], questions_answered: [], failed_jobs: [] };
}

function dayData(date) {
  return DATA.days[date] || emptyDay(date);
}

function toISO(dt) {
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  const d = String(dt.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function parseDay(date) {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function fmtFull(date) {
  return parseDay(date).toLocaleDateString(undefined, {
    weekday: "short", day: "numeric", month: "short", year: "numeric"
  });
}

function fmtShort(date) {
  return parseDay(date).toLocaleDateString(undefined, { day: "2-digit", month: "short" });
}

function relLabel(date) {
  if (date === DATA.today) return "Today";
  if (date === DATA.yesterday) return "Yesterday";
  return parseDay(date).toLocaleDateString(undefined, { weekday: "long" });
}

function timeOnly(stamp) {
  const match = String(stamp || "").match(/(\d{2}:\d{2})/);
  return match ? match[1] : "—";
}

function renderDates() {
  const list = document.getElementById("dateList");
  list.innerHTML = "";
  const dates = DATA.dates.length ? DATA.dates : [DATA.today];

  dates.forEach((date) => {
    const day = dayData(date);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "date-btn" + (date === state.date ? " active" : "") + (day.total_applied ? "" : " empty");
    btn.innerHTML = `
      <span class="d-main">
        <span class="d-rel">${esc(relLabel(date))}</span>
        <span class="d-full">${esc(fmtFull(date))}</span>
      </span>
      <span class="d-count">${day.total_applied}</span>`;
    btn.addEventListener("click", () => {
      state.date = date;
      state.company = null;
      state.query = "";
      document.getElementById("jobSearch").value = "";
      renderAll();
    });
    list.appendChild(btn);
  });
}

function renderSummary() {
  const day = dayData(state.date);
  const cards = [
    { k: "Applied", v: day.total_applied, s: fmtFull(state.date) },
    { k: "Companies", v: day.total_companies, s: "unique companies" },
    { k: "Answers filled", v: day.questions_answered.length, s: "recruiter questions" },
    { k: "Failed / skipped", v: day.failed_jobs.length, s: "attempts that did not go through" },
  ];

  document.getElementById("summaryCards").innerHTML = cards.map((c) => `
    <div class="card">
      <div class="k">${esc(c.k)}</div>
      <div class="v">${c.v}</div>
      <div class="s">${esc(c.s)}</div>
    </div>`).join("");

  document.getElementById("selectedLabel").textContent = `${relLabel(state.date)} · ${fmtFull(state.date)}`;
  document.getElementById("downloadDay").href = `daily/${state.date}.json`;
  document.getElementById("pageSub").textContent = `${day.total_applied} applications on ${fmtFull(state.date)}`;
}

function renderChart() {
  const chart = document.getElementById("chart");
  const dates = [...DATA.dates].sort();
  const recent = dates.slice(-14);

  if (!recent.some((date) => dayData(date).total_applied)) {
    chart.innerHTML = '<div class="chart-empty">No applications recorded yet.</div>';
    return;
  }

  const max = Math.max(...recent.map((date) => dayData(date).total_applied), 1);
  chart.innerHTML = "";

  recent.forEach((date) => {
    const day = dayData(date);
    const height = day.total_applied ? Math.max(6, Math.round((day.total_applied / max) * 132)) : 4;
    const col = document.createElement("div");
    col.className = "bar-col" + (date === state.date ? " selected" : "");
    col.title = `${fmtFull(date)}: ${day.total_applied} applications`;
    col.innerHTML = `
      <div class="bar-val">${day.total_applied || ""}</div>
      <div class="bar-track"><div class="bar" style="height:${height}px"></div></div>
      <div class="bar-lbl">${esc(fmtShort(date))}</div>`;
    col.addEventListener("click", () => {
      state.date = date;
      state.company = null;
      state.query = "";
      document.getElementById("jobSearch").value = "";
      renderAll();
    });
    chart.appendChild(col);
  });
}

function renderCompanies() {
  const day = dayData(state.date);
  const grid = document.getElementById("companyGrid");
  const hint = document.getElementById("companyHint");

  if (!day.companies.length) {
    grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1"><div class="big">🏢</div><div>No companies for this day.</div></div>';
    hint.textContent = "";
    return;
  }

  hint.textContent = `${day.companies.length} companies · click one to filter its jobs`;
  grid.innerHTML = day.companies.map((company) => {
    const roles = company.roles.slice(0, 3).map((role) => `<li title="${esc(role)}">${esc(role)}</li>`).join("");
    return `
      <div class="company-card${state.company === company.name ? " active" : ""}" data-company="${esc(company.name)}">
        <div class="company-top">
          <div class="company-name">${esc(company.name)}</div>
          <div class="company-count">${company.count}</div>
        </div>
        <ul class="company-roles">${roles}</ul>
      </div>`;
  }).join("");

  grid.querySelectorAll(".company-card").forEach((card) => {
    card.addEventListener("click", () => {
      const name = card.getAttribute("data-company");
      state.company = state.company === name ? null : name;
      state.query = "";
      document.getElementById("jobSearch").value = "";
      renderCompanies();
      renderJobs();
      updateFilterChip();
      document.getElementById("jobsPanel").scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}

function filteredJobs() {
  const day = dayData(state.date);
  const query = state.query.trim().toLowerCase();
  return day.jobs.filter((job) => {
    if (state.company && job.company !== state.company) return false;
    if (!query) return true;
    return `${job.company} ${job.title}`.toLowerCase().includes(query);
  });
}

function renderJobs() {
  const jobs = filteredJobs();
  const body = document.getElementById("jobsBody");
  const empty = document.getElementById("jobsEmpty");
  const emptyText = document.getElementById("jobsEmptyText");

  body.innerHTML = jobs.map((job, index) => {
    const url = /^https?:\/\//i.test(job.url) ? job.url : "";
    const role = url
      ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(job.title)}</a>`
      : esc(job.title);
    return `
      <tr>
        <td class="idx">${index + 1}</td>
        <td class="company">${esc(job.company)}</td>
        <td class="role">${role}</td>
        <td class="time">${esc(timeOnly(job.applied_at))}</td>
      </tr>`;
  }).join("");

  if (jobs.length) {
    empty.style.display = "none";
  } else {
    empty.style.display = "block";
    emptyText.textContent = state.company || state.query
      ? "No jobs match this filter."
      : "No applications recorded for this day.";
  }
}

function updateFilterChip() {
  const chip = document.getElementById("filterChip");
  const text = document.getElementById("filterChipText");
  if (state.company) {
    chip.classList.add("show");
    text.textContent = `Company: ${state.company}`;
  } else {
    chip.classList.remove("show");
    text.textContent = "";
  }
}

function renderFoot() {
  document.getElementById("footTotal").textContent = DATA.all_time.applications;
  document.getElementById("footCompanies").textContent = DATA.all_time.companies;
  document.getElementById("footDays").textContent = DATA.all_time.days;
}

function renderAll() {
  renderDates();
  renderSummary();
  renderChart();
  renderCompanies();
  renderJobs();
  updateFilterChip();
}

function init() {
  if (!state.date) {
    state.date = DATA.dates.includes(DATA.today) ? DATA.today : (DATA.dates[0] || DATA.today);
  }
  if (!DATA.dates.includes(state.date)) DATA.dates.unshift(state.date);

  document.getElementById("jobSearch").addEventListener("input", (event) => {
    state.query = event.target.value;
    state.company = null;
    renderCompanies();
    renderJobs();
    updateFilterChip();
  });

  document.getElementById("clearFilter").addEventListener("click", () => {
    state.company = null;
    state.query = "";
    document.getElementById("jobSearch").value = "";
    renderCompanies();
    renderJobs();
    updateFilterChip();
  });

  renderFoot();
  renderAll();
}

init();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    daily_dir, dashboard = refresh()
    print(f"Daily reports: {daily_dir}")
    print(f"Dashboard:     {dashboard}")
