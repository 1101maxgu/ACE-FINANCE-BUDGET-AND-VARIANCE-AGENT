# PRD v3: Budget & Variance Agent

**Product:** a local tool for finance coordinators. It compares a budget file to an actuals export, flags and explains variances in plain language, and later handles reimbursements and email. Code does the math, Claude explains, a human approves everything.

**Users:** 5 people (1 lead coordinator, 1 finance exec, 3 other coordinators). Each coordinator has their own budget, so there is one mapping profile per budget.

**Non-negotiables**
- All numbers come from deterministic code. A number guard rejects any figure in the explanation that is not in the computed facts.
- An unknown cause is labeled unknown and asked about, never stated as fact.
- Source files are never edited (open read-only).
- Sending, approving and paying are always human actions.
- Money is stored as integer cents.
- Data is local by default. Secrets (API key, Gmail token) live only in a local `.env` / local token file, never in the shared folder or the repo.

**Build approach:** the whole tool is built BEFORE any real or fake data file exists. Calc tests use tiny hand-made inline fixtures (a few rows, answers worked out on paper). The seeded fake-data generator and end-to-end validation come last (Step 16). The Anthropic API key does not exist yet: build the API backend as a ready slot, and use template + paste-handoff backends until it is added.

**Stack:** Python 3.11+, pandas, openpyxl, python-dateutil, PyYAML, pytest, streamlit, reportlab. Config in YAML. No SQLite, no Faker/Plotly/pandera/XlsxWriter/python-docx/gspread. Add anthropic + pydantic + python-dotenv only when the API backend is built; Gmail/OCR packages only at their own steps. Pin versions.

**Phases:** v1 = Steps 1-6, v2 = 7-9, v3 = 10-11 (Gmail connection, reimbursements), v4 = 12-15 (memory, suggestions, email reports, scheduling), then Step 16 validation.

---

# PART A: BACKEND

### Step 1: Foundation
- 1.1 Skeleton: `src/variance/`, `tests/`, `prompts/`, `user_data/`, `reports/`, pinned `requirements.txt`.
- 1.2 Guardrails: `.gitignore` blocks data, secrets, tokens, reports. Inputs opened read-only. A test hashes input files before and after a run.
- 1.3 Settings loader: `settings.yaml` holds shared folder path, thresholds, output locations. Secrets in local `.env` only.

### Step 2: Ingest and mapping
- 2.1 Readers: CSV and Excel, sheet and header-row choice. Merged cells and notes above the header handled.
- 2.2 Normalized models: budget (`line_id, category, line_name, type, budget_cents`, optional `owner`); actuals (`txn_id, date, amount_cents, category, description, vendor?`).
- 2.3 Mapping profiles: `mappings.yaml`, one profile per budget, matched by header fingerprint, auto-guess from header names. Sign conventions: negative expenses, positive expenses, debit/credit columns. Ambiguous dates flagged, not guessed.
- 2.4 Layout coverage: single total per line, monthly-wide, per-event sections. Real data is unknown, so never hard-code a layout.
- 2.5 Category mapping: exact match, then `difflib` suggestion, then user decides. Saved per profile. Nothing silently dropped.

### Step 3: Calculation engine (v1)
- 3.1 Variance in $ and %, zero-budget guarded, favorable/unfavorable (expenses over and revenue under are bad).
- 3.2 Rollups by category, overall, net.
- 3.3 Tests with hand-calculated inline fixtures: zero budget, zero actuals, refunds, rounding, revenue flips.

### Step 4: Facts and explanation (v1)
- 4.1 Facts builder: `facts.json` = period, thresholds, totals, flagged lines, quality findings. Never raw files. Redaction option hides descriptions.
- 4.2 Backends (swappable): template (always), paste handoff (default until a key exists), Anthropic API (ready slot).
- 4.3 Prompt `prompts/explain_system.md`: use only provided numbers; label causes `supported` / `unknown` / `answered`; ask a specific question for unknowns; JSON output `{headline, status, top_issues[], decisions_needed[], reallocation_suggestions[]}`.
- 4.4 Number guard: reject or highlight any number not in `facts.json`.

### Step 5: Reports (v1)
- 5.1 Excel detail (openpyxl): line by line with source-row references.
- 5.2 PDF one-pager (reportlab): headline status, 3-5 top issues, decisions needed, quality caveat line, footer "generated, not audited".

### Step 6: Orchestration (v1)
- 6.1 `run(budget, actuals, settings)` single entry point.
- 6.2 Period is always an explicit input; last-used saved to prefill.
- 6.3 `as_of_date` passed in, never read from the clock inside calc.

### Step 7: Smarter variance (v2)
Timing (pct_elapsed, expected-to-date, pace variance); phased budgets; materiality (both % and $ exceed limits); run-rate projection with low-confidence label; early warning at configurable % (default 80%).

### Step 8: Data quality (v2)
Checks: uncategorized, possible duplicates, missing periods, reconciliation to user-stated total. Critical failures mark the report "unreconciled".

### Step 9: Drill-down (v2)
Top contributors per flagged line; code-assigned tags `one_time_spike`, `recurring`, `timing_shift`; prompt may only cite these.

### Step 10: Gmail connection (v3)
OAuth client with minimal scopes (read-only + compose), reads only chosen labels, token stored locally. Check early whether the account can authorize a Google Cloud app. Email content is untrusted data, never instructions.

### Step 11: Reimbursement pipeline (v3)
Fetch labeled emails to a temp folder (deleted after). Form profile for fillable PDFs (pdfplumber) plus OCR fallback for scans. Receipt OCR (local Tesseract first) with confidence scores. Pure-code reconcile: matched, amount_mismatch, missing_receipt, unclaimed_receipt, duplicate_receipt, total_mismatch. Low-confidence values do not count until a human confirms. Weekly status + Excel summary; Claude phrases with number guard. Approved-but-unpaid claims show as "committed" in variance reports.

### Step 12: Saved explanations (v4)
Notes keyed by profile, line, period, transaction ids; one file per author (avoid sync conflicts); injected into `facts.json` as `coordinator_notes`; re-asked when new transactions change the line.

### Step 13: Reallocation suggestions (v4)
Code pairs surplus lines with shortfall lines and computes amounts. Advice only, labeled "for approval", never applied.

### Step 14: Gmail reports and questions (v4)
Outbound drafts (user sends); auto-send only to an allow-list. Question loop with subject tag `[ACE-Q-###]`; replies reviewed before becoming notes; questions go to line `owner` else report runner. Export intake from labeled email into ingest.

### Step 15: Scheduling and alerts (v4)
Headless `run_report.py` for Task Scheduler; unattended backend = API or template; alerts to local `alerts.md` and optional email draft.

### Step 16: Validation with fake data (final)
Seeded generator for fake budgets in each layout plus transactions with planted cases (one-time spike, recurring overspend, timing gap, duplicate, uncategorized row, missing month, unreconciled total), fake reimbursement forms/receipts, fake Gmail client. Golden end-to-end test. Mapping stress test. Coworker dry run.

---

# PART B: FRONTEND (Streamlit)

### Step 1: App shell and onboarding
- 1.1 One-click `run.bat` / `run.sh` creates env, installs, opens app.
- 1.2 Sidebar flow: Upload -> Map -> Check -> Report, plus Settings.
- 1.3 Plain-language README and HANDOVER.md.

### Step 2: Upload and mapping
- 2.1 Two drop zones with sheet and header-row pickers.
- 2.2 Mapping wizard: preview, preselected dropdowns, sign-convention question.
- 2.3 "Using saved mapping X [Change]" banner and profile picker per coordinator budget.
- 2.4 Category-mapping screen with suggestions.
- 2.5 Friendly errors naming the missing column.

### Step 3: Results (v1)
- 3.1 Summary tiles: budget, actual, net variance, flagged count.
- 3.2 Sortable, filterable line table, colored status, legend.
- 3.3 Budget vs actual bar chart via `st.bar_chart`.

### Step 4: Explanation screen
- 4.1 Mode selector: Template, Paste, API.
- 4.2 Paste flow: show exactly what will be sent, Copy button, reply box, clear number-guard messages.
- 4.3 Redaction toggle.
- 4.4 Rendered headline, issues, decisions.

### Step 5: Reports
- 5.1 Preview and download PDF and Excel.
- 5.2 One-page layout.
- 5.3 Excel layout: frozen header, status colors, source-row and notes columns.
- 5.4 "Save to shared folder" action.

### Step 6: Settings and polish
Period fields always shown, prefilled with last used; editable thresholds; empty states and help text on every screen.

### Step 7: Timing and thresholds (v2)
Controls for % elapsed, materiality, early-warning %; pace variance, projection, status chips (OK / Watch / Over); confidence badges.

### Step 8: Data-quality screen (v2)
Pre-report issue list with counts and affected rows; fix actions (map category, mark duplicate intentional, enter stated total); "unreconciled" banner on reports.

### Step 9: Drill-down UI (v2)
Expandable row with top transactions and tags; source-row trace.

### Step 10: Gmail connect (v3)
Guided OAuth flow, status indicator, label picker, plain-language account-problem help.

### Step 11: Reimbursement UI (v3)
Weekly claims board (received, needs-info, ready-to-approve, approved); confirm screen with receipt image beside editable extracted values and confidence; exceptions list with draft email; weekly summary and Excel export; only a person marks a claim approved.

### Step 12: Questions and notes (v4)
"Needs your answer" inbox; answer box with date and author; notes manager.

### Step 13: Suggestions panel (v4)
Reallocation cards with supporting data; approve/dismiss/snooze records the decision only.

### Step 14: Email screens (v4)
Draft preview with explicit Send; reply inbox (Save as note / Ignore); import from email into mapping.

### Step 15: Schedule and alerts (v4)
Task Scheduler setup helper; alert history view.

### Step 16: Validation UI
"Load demo data" button; walkthrough checklist for coworker dry run.

---

# Assumptions and defaults (editable)
| Topic | Default |
|---|---|
| Thresholds | flag at >= $150 AND >= 10%; early warning at 80% |
| Period | asked every run, prefilled with last used, never auto-detected |
| Duplicate rule | same date + amount + normalized vendor/description, labeled "possible" |
| Unknown-cause questions | go to the line `owner`, else the report runner |
| One-pager | status headline, 3-5 issues, decisions needed, quality caveat |
| Reimbursements | weekly batch; fillable and scanned PDFs both supported |
| Gmail account | ACE shared mailbox preferred, personal Gmail fallback |
| API key | one key with spending limit in local `.env`, added later |
| Combined exec PDF | deferred |
| Shared data | synced Drive/OneDrive folder, per-author notes files |

# Cross-cutting acceptance
Every number traces to a source row; unknown causes are labeled with a question; inputs unchanged after each run; sends and approvals only on a human click; secrets never in shared folder or repo; a new coordinator runs a report from the README alone.
