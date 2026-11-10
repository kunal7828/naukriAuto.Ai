<div align="center">

# 🤖 Naukri AutoAI

**An intelligent, resume-aware job application assistant for [Naukri.com](https://www.naukri.com)**

Automate repetitive application steps, answer recruiter questionnaires with AI, and keep a hard daily safety limit — all from your desktop.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Playwright-Chromium-green)](https://playwright.dev/)
[![LangChain](https://img.shields.io/badge/LangChain-Groq-orange)](https://www.langchain.com/)
[![License](https://img.shields.io/badge/license-personal%20use-lightgrey)]()

</div>

---

## Table of Contents

- [What is Naukri AutoAI?](#what-is-naukri-autoai)
- [Why this exists](#why-this-exists)
- [How it works](#how-it-works)
- [Key Capabilities](#key-capabilities)
- [Tech Stack](#tech-stack)
- [Architecture / Project Structure](#architecture--project-structure)
- [Setup](#setup)
  - [1. Clone & create a virtual environment](#1-clone--create-a-virtual-environment)
  - [2. Install dependencies](#2-install-dependencies)
  - [3. Configure `.env`](#3-configure-env)
  - [4. Add resume & prompt context](#4-add-resume--prompt-context)
- [Usage](#usage)
- [The Curated Answer Sheet](#the-curated-answer-sheet)
- [Reports & Dashboard](#reports--dashboard)
- [How the Daily Limit Works](#how-the-daily-limit-works)
- [Testing](#testing)
- [Configuration Reference](#configuration-reference)
- [Local Data & Privacy](#local-data--privacy)
- [Troubleshooting](#troubleshooting)
- [Responsible Use](#responsible-use)
- [Disclaimer](#disclaimer)

---

## What is Naukri AutoAI?

**Naukri AutoAI** is a desktop automation assistant that applies to Naukri.com jobs on your behalf. It:

1. Logs into your Naukri account in a real Chromium window,
2. Opens job listings, selects the most relevant ones (your preferred roles first),
3. Applies in batches of up to 5 using Naukri's quick-apply button,
4. Answers recruiter questionnaires (experience, skills, notice period, salary, location…) using your resume — **with your explicit answers preferred over AI guesses**,
5. Stops exactly at a configurable daily limit (default **49/day**), and
6. Logs everything to JSON/Excel reports and an HTML dashboard you can open in a browser.

It is designed to be **safe by construction**: it never applies to more jobs than your daily limit, it verifies applications where possible, it relaunches the browser if Chromium crashes, and it keeps personal data off the repo.

> ⚠️ This is a **personal automation tool**, not a hosted service. It runs on your machine with your Naukri account and your Groq API key.

---

## Why this exists

Applying to jobs on Naukri means repeating the same steps dozens of times a day:

- Opening each listing → checking details → clicking Apply
- Filling the same recruiter questions again and again: *years of experience, notice period, current location, willingness to relocate, salary expectations…*
- Tracking what you already applied to — and trying not to exceed the sensible daily limit Naukri expects

Doing this manually is slow and error-prone. Naukri AutoAI turns it into a guided, supervised flow that respects a **49 applications/day** ceiling, remembers every answer it gave, and lets you **override any answer** permanently in one sheet.

---

## How it works

```text
main.py
  └─ acquire single-instance lock
  └─ app.flows.runner.run_bot()
        │
        ├─ launch Chromium (with GPU-off & background-throttling flags)
        ├─ login_page.handleLogin()          → Naukri homepage (reuses saved session if any)
        ├─ load today's applications (reports + durable log)
        │     └─ already at limit? → stop before doing any work
        │
        └─ while under daily limit:
              ├─ open jobs listing (recommended jobs tabs: Applies / Handpicked / You might like …)
              ├─ pick up to 5 jobs whose title matches PREFERRED_ROLES first (⭐ preferred, ▫️ fallback)
              ├─ click Naukri's page-level "Apply N Job(s)" button
              ├─ close external company tabs opened by the apply
              ├─ questionnaire_page.handle_questionnaire():
              │     ├─ read the recruiter bot's question
              │     ├─ answer from: your curated sheet → answer cache → AI
              │     └─ click Save / press Enter
              ├─ verify outcome (success / error / unknown toast)
              ├─ append confirmed batch to data/applied_log.jsonl
              └─ if no selectable jobs anywhere → search by role keyword (search fallback)
        │
        └─ generate reports (JSON + Excel)
             generate data/reports/dashboard.html
             generate/refresh data/resume/Question_Answers.xlsx
```

**The core loop is deliberately simple and defensive:** every batch is written to a durable log immediately, the daily limit is counted from *reports + durable log* (never from memory alone), and a browser crash triggers an automatic relaunch with progress intact.

---

## Key Capabilities

### ✅ Application engine
- **Bulk select + bulk apply** in batches of 5 (Naukri's page-level Apply button).
- **Role-priority selection** — configure your preferred roles (`PREFERRED_ROLES`) and the bot ticks them first wherever they appear on the page.
- **Job search fallback** — if the recommendation tabs run dry, the bot searches Naukri by role keyword and keeps applying, so your daily quota is actually reachable.
- **Walk-in / non-quick-apply jobs are skipped** automatically.
- **External company-site tabs opened by Apply are closed** right away.

### ✅ Daily safety limit
- **49 applications per day** (configurable).
- Count rebuilds from persisted reports + an append-only durable log, so **restarts and hard kills never overshoot the limit**.
- Failed applications are skipped for the day but retryable tomorrow.
- Single-instance lock prevents two bots running at once.

### ✅ Recruiter questionnaires
- Detects the recruiter chat panel, extracts each question, and answers:
  1. **Your curated answer** (from `Question_Answers.xlsx`) — always wins,
  2. Cached previous answer (local Q&A cache),
  3. AI (Groq, using your resume + system prompt).
- Handles both free-text and multiple-choice questions with a smart matcher (exact → substring → word-overlap → "Skip this question").
- **Your answer sheet is refreshed after every run** and your edits survive forever.

### ✅ Reliability & resilience
- **Auto-relaunch on browser crash** — Chromium dying mid-run no longer aborts the session.
- **Liveness checks** — a dead browser raises instead of burning the "no jobs" budget.
- **Diagnostics** — per-run logs, tracebacks and screenshot on error under `data/diagnostics/`.
- **Session persistence** — `storage_state.json` reuses your Naukri login between runs.

### ✅ Reports & dashboard
- Every run writes `data/reports/report_<timestamp>.json` + `.xlsx`.
- A merged per-day summary, `data/reports/daily/YYYY-MM-DD.json`.
- A self-contained **HTML dashboard** (`data/reports/dashboard.html`) showing today / yesterday / previous days with applied jobs, companies, and QA log.
- An editable **curated answer sheet** with every question the bot ever answered.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Browser automation | **Playwright** (Chromium, Page Object Model) |
| LLM | **Groq** (`openai/gpt-oss-120b`) via **LangChain** |
| Semantic answer cache | **Sentence-Transformers** (embeddings, local) |
| Config | **pydantic-settings** + `.env` |
| Reports | JSON + **openpyxl** (Excel) |
| Dashboard | Self-contained HTML/CSS/JS (no dependencies) |
| Persistence | JSON / JSONL files + SQLite (LangChain cache) |

---

## Architecture / Project Structure

Page Object Model — one module per Naukri page/panel, so the code matches what you see on screen.

```text
app/
  pages/                  # ── Page Object Model layer ─────────────────
    login_page.py           Login flow (Naukri open, sign in, saved-session detection)
    jobs_page.py            Jobs listing: open tabs, role search, select job cards
    apply_page.py           Bulk Apply, outcome detection, external tab cleanup
    questionnaire_page.py    Recruiter chat panel: questions, options, answers
  flows/
    runner.py               Orchestration: browser sessions, retries, daily limit, reporting
  ai/                     LLM init, AI answer generation, embeddings
  config/                 pydantic-settings, reads .env
  database/               db.json cache utilities
  repository/             Q&A cache lookup / save (exact + semantic)
  utils/                  Shared helpers (see below)
    human.py                Human-like delays, typing, mouse movement
    lock.py                Single-instance file lock (stale-lock detection)
    report.py               Per-run JSON/Excel reports
    daily_report.py         Merge + HTML dashboard generator
    applied_log.py          Append-only durable application log
    answer_sheet.py         Curated Question_Answers.xlsx (read/refresh)
    diagnostics.py          Per-run logs, screenshots, error records
    notifier.py             (Optional) email/SMS completion notification
    file_loader.py          Loads resume / prompts
    process_question.py     Question normalization
main.py                   Application entry point
tests/                    Unit tests (daily limit, answer sheet, role priority)
data/
  resume.txt                Your professional profile used by the AI
  resume/Question_Answers.xlsx  Your curated answers (editable)
  reports/                  Generated reports + dashboard.html (gitignored)
```

**Design principle:** *pages* know how to talk to Naukri; *flows* decide when; *ai* decides what to say; *utils* provide plumbing. No page module imports another page module — they share only utils.

---

## Setup

### 1. Clone & create a virtual environment

```bash
git clone https://github.com/<your-username>/naukriAuto.Ai.git
cd naukriAuto.Ai
```

Windows:
```powershell
python -m venv venv
.\venv\Scripts\activate
```

macOS/Linux:
```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

> **Python 3.10+** recommended (3.12 known to work). Stdlib's `unittest` runs the test suite — nothing extra to install.

### 3. Configure `.env`

Create a `.env` file in the project root (**never commit it**):

```env
NAUKRI_EMAIL="you@example.com"
NAUKRI_PASSWORD="your_naukri_password"
GROQ_API_KEY="gsk_your_groq_key"
```

Minimal is enough — everything else has sensible defaults.

### 4. Add resume & prompt context

Edit these files in `data/` so the AI knows who you are:

- **`data/resume.txt`** — your professional profile (experience, skills, notice period, expected CTC, location…). This is the source of truth for AI answers.
- **`data/system_prompt.txt`** — rules for how the AI should answer (never invent facts, salary policy, "Not specified" on unknowns…).
- **`data/human_prompt.txt`** — prompt template injecting resume + options + question.
- **`data/resume/Question_Answers.xlsx`** — the editable answer sheet (created automatically after the first run).

---

## Usage

```bash
python main.py
```

You'll see a Chromium window open, log in, and start applying. The console logs each batch (`⭐ Selected job …`, `🎉 Bulk apply completed …`, `📈 Total applied today: X/49`).

- The bot **stops at 49 applications for the day** — even if restarted mid-day.
- Press `Ctrl+C` to stop early; progress is saved.
- Restarting is safe: the daily count survives because it's read from disk.

### Tests

```bash
python -m unittest discover -s tests -v
```

12 tests covering the daily-limit counting, durable log, role-priority ranking and curated-answer overrides.

---

## The Curated Answer Sheet

`data/resume/Question_Answers.xlsx` is the most important file for answer quality. It has two tabs:

### `Q&A Log`
| Column | What it means |
|---|---|
| `#`, `Question`, `Options Seen` | What the recruiter asked |
| `Answer Given` | What the bot answered on Naukri |
| `Times Asked`, `Last Asked`, `Source` | History across all runs |
| **`Your Answer`** (yellow) | **← EDIT THIS COLUMN** |
| `Notes` | Your notes |

**Fill `Your Answer` with exactly what you want the bot to say.** From then on, that answer is used verbatim for that question — it always wins over cache and AI. Edits are preserved across every automatic refresh.

### `Profile (ODS)`
Your full profile sheet, flattened for quick reference.

Rebuild it anytime (your edits are kept):

```bash
python -m app.utils.answer_sheet
```

> Tip: after a few runs, open the sheet and fix the rows where the bot said `Not specified` or a wrong value. Your next run will answer them perfectly.

---

## Reports & Dashboard

Every run produces:

| File | Purpose |
|---|---|
| `data/reports/report_YYYY-MM-DD_HH-MM-SS.json` | Raw per-run data |
| `data/reports/report_YYYY-MM-DD_HH-MM-SS.xlsx` | Human-friendly Excel version |
| `data/reports/daily/YYYY-MM-DD.json` | Merged summary for the day |
| `data/reports/dashboard.html` | Self-contained HTML dashboard |

The dashboard shows **today / yesterday / previous days**, applied jobs, company names, answers given, and skipped/failed attempts — open it in any browser, no server needed.

---

## How the Daily Limit Works

The hard ceiling is `DAILY_APPLY_LIMIT` (default **49**). It is enforced exactly:

1. Every confirmed apply is appended to **`data/applied_log.jsonl`** (one JSON line per job) *as soon as the batch finishes*.
2. On startup, the limit is recomputed as the number of **distinct job URLs applied today**, read from:
   - the durable log (survives crashes), **and**
   - every `data/reports/*.json` (older runs).
3. Both sources are deduplicated by URL, and today's count caps each batch: `batch_size = min(MAX_BATCH_SIZE, remaining)`.
4. If the count is already 49, the bot logs and stops **before doing any work**.

This means:
- Restarting never double-applies.
- A hard kill (power loss, crash) loses nothing.
- Failed applications are logged as failed and are **not** counted toward the limit — but they are skipped for the rest of the day.

---

## Testing

```bash
python -m unittest discover -s tests -v
```

| Suite | What it covers |
|---|---|
| `tests/test_daily_limit.py` | Daily-count correctness incl. crash-safety, durable log, failed-job skip |
| `tests/test_answer_sheet.py` | Curated-answer overrides, edit preservation across refreshes |
| `tests/test_select_jobs.py` | Role-priority ranking, job-key deduplication |

---

## Configuration Reference

All settings live in `.env` and are validated by `app/config/config.py`:

| Setting | Default | Description |
|---|---|---|
| `NAUKRI_EMAIL` | *(required)* | Your Naukri login |
| `NAUKRI_PASSWORD` | *(required)* | Your Naukri password |
| `GROQ_API_KEY` | *(required)* | Groq API key |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | LLM used for answers |
| `LLM_TEMPERATURE` | `0.3` | Creativity of answers |
| `DAILY_APPLY_LIMIT` | `49` | Hard daily apply ceiling |
| `MAX_BATCH_SIZE` | `5` | Jobs per bulk-apply batch |
| `MAX_EXPERIENCE_YEARS` | `10` | Skip jobs requiring more experience |
| `PREFERRED_ROLES` | `""` | Comma-separated roles, in priority order |
| `PREFERRED_LOCATIONS` | `""` | Preferred locations (used by job search) |
| `HEADLESS` | `false` | Run browser without a window |
| `SLOW_MO_MS` | `60` | Playwright slow-motion in ms |
| `VIEWPORT_WIDTH` / `VIEWPORT_HEIGHT` | `1280` / `720` | Browser viewport |
| `STORAGE_STATE_PATH` | `storage_state.json` | Saved login session |
| `DIAGNOSTICS_DIR` | `data/diagnostics` | Logs / screenshots |
| `SCREENSHOT_ON_ERROR` | `true` | Screenshot when an error is logged |
| `SMTP_*`, `REQUIRE_APPROVAL`, `DRY_RUN` | — | Reserved / optional |

---

## Local Data & Privacy

Everything sensitive stays on your machine and is **gitignored**:

| File | Contents |
|---|---|
| `.env` | Your credentials & API key |
| `data/resume.txt` | Your professional profile |
| `data/resume/` | Your answer sheet & profile sheet |
| `data/reports/` | Your application history |
| `data/applied_log.jsonl` | Durable daily-limit log |
| `data/db.json`, `naukri_autoai_memory.db` | Q&A caches |
| `data/diagnostics/` | Logs & screenshots |
| `storage_state.json` | Saved Naukri session cookies |

If you fork this repository, **never commit these files**. The `.gitignore` is set up to protect them — double-check with `git status` before pushing.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Browser closes mid-run (`TargetClosedError`) | GPU driver crash — the bot auto-relaunches; check `data/diagnostics/` for screenshots & tracebacks |
| "Another instance is already running" | A stale lock — delete `naukri_autoai.lock` (or a crashed bot left it; it's auto-cleared if the PID is dead) |
| Bot stops early at ~37/49 | Recommendation tabs ran dry — the role-search fallback kicks in; ensure `PREFERRED_ROLES` is set |
| Login fails every run | Saved session expired — delete `storage_state.json` and re-login |
| All questions answered `Not specified` | Review `data/resume.txt` completeness; add `Your Answer` rows in `Question_Answers.xlsx` |
| Wrong salary quoted | Set expected CTC in `data/resume.txt` **and** in Naukri (Settings → Job Preferences) |

---

## Responsible Use

- Use this **only with your own Naukri account** and in accordance with Naukri's Terms of Service.
- This tool automates *repetitive* steps; it does not guarantee responses from employers.
- Always review your answers. The AI follows `data/system_prompt.txt` — it will not invent facts, and it says `Not specified` when it doesn't know.
- Keep your credentials private; treat `.env`, `data/resume/`, and `storage_state.json` as secrets.

## Disclaimer

This project is provided as-is, for personal productivity. The author is not responsible for how it is used, account restrictions imposed by Naukri, or inaccuracies in AI-generated answers. You are responsible for the content of your applications.

---

<div align="center">

⭐ If this saves you time, consider starring the repo.

</div>
