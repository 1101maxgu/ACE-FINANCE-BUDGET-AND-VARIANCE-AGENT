# Backend contract notes (Steps 1-5)

No renames from the agreed interface. Clarifications and small additions:

- Import: `src/` must be on `sys.path` (pytest.ini does it for tests; app.py needs `sys.path.insert(0, "src")`).
- Files: settings = `user_data/settings.yaml` (template: `settings.template.yaml`), mappings = `user_data/mappings.yaml`.
  `load_profiles/save_profile/find_profile_by_fingerprint/save_category_map/load_settings/save_settings`
  take an optional `path=` (used by tests).
- `guess_mapping(df, kind)` returns `{kind, sheet, header_row, columns{field: header|None}, fingerprint, ...}`.
  Budget adds `layout` ('total'|'monthly_wide'|'sections'), `month_columns`, `type_default`.
  Actuals adds `sign` ('negative_expenses'|'positive_expenses'|'debit_credit') and `date_order` (None|'dmy'|'mdy').
  The UI must set `sheet` and `header_row` from its pickers before saving/loading. `preview()` and
  `load_*` use the same `sheet`/`header_row`. `ingest.guess_header_row(file, sheet)` is an extra helper.
- `save_profile(name, m)`: `m` is one guess_mapping dict (stored under its `kind`) or `{'budget':..,'actuals':..}`.
  Profile = `{budget, actuals, category_map}`. `load_budget/load_actuals` accept either the single mapping or the whole profile.
- Actuals sign: normalized `amount_cents` is POSITIVE = money out, NEGATIVE = money in (refund or revenue).
- Dates that could be day-first or month-first raise IngestError unless `date_order` is set or the file proves it.
- Extra columns: both loaders add `source_row` (1-based row in the file); `df.attrs['skipped_rows']` lists
  skipped total/blank-ish rows as `(row, text)`.
- `suggest_categories` rows also carry `suggestion_label, count, total_cents`. `suggestion` and the saved
  category_map values are budget **line_id**s (`''` = leave as unbudgeted). status: saved|exact|ambiguous|suggested|unmatched.
  `compute` auto-uses unique exact matches for categories missing from the map; the rest become `UNBUDGETED:<cat>` lines.
- `compute`: `variance = actual - budget`; revenue actual = -sum(amount_cents). `variance_pct` is NaN for zero budget
  (None in facts). `flagged` = |var| >= flag_min_cents AND (budget 0 OR |pct| >= flag_pct), either direction.
  Period filter: `settings['period']` {label,start,end} and `as_of_date` (cutoff); excluded rows counted in totals.
  `Result` = `.lines, .totals, .txns, .as_of_date, .period`.
  Settings keys: `flag_pct`, `flag_min_cents`, `period`, `last_period`, `reports_dir`, `shared_folder`, `explain_mode`, `redact`.
- Explanation schema: `status` is 'on_track'|'watch'|'off_track'; each `top_issues` item is
  `{line_id,title,detail,cause{label: supported|unknown|answered,text},question}`.
- `parse_pasted_reply` returns `(None, problems)` only if no usable JSON/schema; otherwise `(dict, problems)`
  where problems include number-guard hits ("Number not in the computed facts: X") for highlighting.
- `number_guard` also allows whole-dollar rounding, numbers inside fact strings (dates, ids) and list lengths.
- `explain.NotConfigured` is raised by `explain_api`.

---
# Steps 6-9, 12, 13 (added)

## Step 6 `variance.pipeline.run(budget_file, actuals_file, settings, profile, as_of_date=None, redact=False, stated_total_cents=None, notes=None, committed=None, intentional_dupes=(), settings_path=None, remember=False) -> dict`
- Returns `{'result', 'facts', 'budget', 'actuals'}`. `profile` = saved profile (`mapping.load_profiles()[name]`, has budget/actuals/category_map).
- `settings['period'] = {label, start, end}` is REQUIRED: ValueError("Please enter the report period (...)") otherwise. Values may be dates; stored as ISO strings.
- `as_of_date` defaults to the period END (never the clock). `remember=True` saves `settings['last_period']` (prefill) to `settings_path`.
- `result.quality` is filled (Step 8).

## Step 7 timing (calc.compute adds columns; all optional, NaN/NA when no period start+end and no override)
- New `settings` keys: `pct_elapsed` (0-100 override, "" = auto from period), `early_warning_pct` (default 80).
- New `.lines` columns: `committed_cents, expected_cents, pace_variance_cents, pace_flagged, projection_cents, projection_variance_cents, projection_confidence ('low'|'medium'|'high'|''), early_warning, chip ('ok'|'watch'|'over'), pct_elapsed (0..1)`.
  The four `*_cents` timing columns are pandas `Int64` (use `pd.isna`). `totals['pct_elapsed']` is percent (e.g. 50.0) or None.
- Phased budgets: monthly_wide budget frames carry a `phasing` column [(header, cents), ...]; expected-to-date uses it (current month prorated by day).
- `compute(..., committed={line_id: cents})` -> `committed_cents` column and `totals['committed_cents']` (does not change actual).
- Materiality = existing `flagged` rule (both % and $). Confidence: low if <25% elapsed or <3 txns; high if complete, or >=50% elapsed with 3+ txns.

## Step 8 `variance.quality`
- `run_checks(budget_df, actuals_df, result, settings, stated_total_cents=None, intentional_dupes=()) -> list[finding]`;
  finding = `{code, severity 'critical'|'warning', message, count, rows (source rows), txn_ids}`.
  Codes: `uncategorized, unmapped_category, possible_duplicate, missing_period, unreconciled(critical)`.
- `is_unreconciled(findings) -> bool`. Fix actions: pass `intentional_dupes=[txn_id,...]`, `stated_total_cents`, and a category_map to `run`.
- `facts['quality_findings']` and `facts['unreconciled']`; Excel/PDF/template headline show UNRECONCILED when true.

## Step 9 `variance.drilldown.drill(result, line_id, n=5) -> {line_id, tags[], top_transactions[{txn_id,date,amount_cents,vendor,description,source_row,tag}]}`
- Tags: `one_time_spike`, `recurring` (per transaction), `timing_shift` (line). Facts' flagged lines carry `tags` and top 3 transactions (with `source_row`, `tag`).

## Facts changes
`build_facts(result, settings, redact=False, notes=None)`: flagged lines now also have timing fields, `tags`, `coordinator_notes`
`[{author,date,text,state 'current'|'stale'}]`; plus top-level `watch_lines`, `reallocation_candidates`, `unreconciled`, `thresholds.early_warning_pct`.

## Step 12 `variance.notes` (one JSON file per author: `<data_dir>/notes/<Author>.json`; `settings.data_dir(settings)` = `shared_folder` or `user_data/`)
- `add_note(settings, author, profile, line_id, period_label, txn_ids, text, date=None) -> note`; `load_notes(settings, profile=None, period=None) -> list`;
  `delete_note(settings, author, note_id)`; `note_state(note, current_txn_ids)`.
- Pass `load_notes(settings, profile, period_label)` as `notes=` to `pipeline.run` / `build_facts`. A `stale` note means new transactions: template re-asks.

## Step 13 `variance.realloc` (advice only; nothing applied)
- `suggest(result, settings) -> [{suggestion_id 'FROM->TO', from_line_id, from_name, to_line_id, to_name, amount_cents, status 'for approval', note}]`.
- `record_decision(settings, author, suggestion_id, 'approved'|'dismissed'|'snoozed', date, snooze_until=None)` (file `<data_dir>/decisions/<Author>.json`),
  `load_decisions(settings)`, `with_decisions(suggestions, decisions, on_date) -> suggestions + {decision, visible}`.
- Template backend puts the candidates in `reallocation_suggestions` as "Move $X from A to B (for approval; advice only)."

## API backend
`explain.explain_api(facts, settings=None, client=None)` now calls Claude (model `settings['api_model']`, default `claude-sonnet-5-5`) using `ANTHROPIC_API_KEY`
from the environment or a local `.env` in the project root. No key -> `NotConfigured`. Unusable reply / number-guard hit -> `explain.ExplainError`.

---
# Steps 10, 11, 14, 15 (added)

New settings keys (defaults in `settings.DEFAULTS`, template in `settings.template.yaml`): `gmail{labels[], credentials_path, token_path, allow_list[],
reimbursement_label, export_label, question_label}`, `runner_email`, `owner_emails{name: email}`, `ocr_confidence` (0.8), `api_model`.
`settings.data_dir(settings)` = `shared_folder` or `user_data/` (notes/, questions/, decisions/, claims.json live here).

## Step 10 `variance.gmail`
- Scopes: gmail.readonly + gmail.compose only. Token + Google app file default to `~/.ace-variance/gmail_token.json` and `credentials.json`
  (`ValueError` if a path is inside `shared_folder`). Email content is untrusted: never put it into prompts/facts.
- Interface `GmailClient`: `account()`, `list_labels() -> [{id,name}]`, `list_messages(label_name)`, `get_message(id) -> {id,subject,from,date,body_text,attachments[{filename,mime,data}]}`,
  `create_draft(to,subject,body,attachments=())`, `send_message(...)`. `InMemoryGmailClient(messages={label: [msg,...]})` is the fake (records `.drafts`, `.sent`, `.reads`). `GoogleGmailClient` is the real one.
- `connect(settings)` (browser OAuth; raises `GmailNotConnected` with plain-language help incl. admin-blocked accounts), `load_client(settings)`, `disconnect(settings)`,
  `status(settings, client=None) -> {connected, account, problem}`, `list_labels(client) -> [names]` (label picker), `chosen_labels(settings)`.
- `read_label(client, settings, label_name)`: ONLY labels in `settings['gmail']['labels']` else `NotAllowed`; every message gets `untrusted=True`.
- `fetched(client, settings, label_name, exts=None)`: context manager, attachments saved to a temp folder deleted on exit; yields `[{..., files:[Path]}]`.
- `make_draft(client, to, subject, body, attachments=()) -> draft_id` (drafts only). `send_if_allowed(client, settings, to, ...)`: only if every recipient is in `gmail.allow_list`
  else `NotAllowed`; nothing in the package calls it automatically (UI "Send" click only).

## Step 11 `variance.reimburse` (needs pdfplumber; OCR needs the Tesseract program, which is optional)
- Forms: `read_form_fields(pdf) -> {field: value}`, `guess_form_profile(fields) -> {claimant, amount, date, description, email, line_id: pdf field|None}`,
  `load_form_profiles(path=None)`, `save_form_profile(name, mapping, path=None)` (file `user_data/form_profiles.yaml`), `read_claim_form(pdf, form_profile, claim_id=None) -> claim`.
- Receipts: `read_receipt(path, claim_id=None, tesseract_cmd=None) -> receipt`, `parse_receipt(lines)`, `receipt_lines(path)`. Text PDFs are read directly (confidence 1.0);
  scans/images need OCR and raise `OcrUnavailable` (plain-language, mentions Tesseract) when it is missing - catch it and show the message.
- Claim = `{claim_id, claimant, email, amount_cents, date, description, line_id, items?[cents], confidence, confirmed, source}`;
  receipt = `{receipt_id, claim_id, amount_cents, date, vendor, confidence, confirmed, source 'text'|'ocr', sha256, file}`.
- `counts(item, threshold)`: amount counts only if `confirmed` or confidence >= threshold (`settings['ocr_confidence']`). `confirm(item, by, amount_cents=None, date=None, vendor=None)` returns a confirmed copy.
- `reconcile(claims, receipts, threshold=0.8) -> {'claims': [{claim_id, status, statuses[], claimed_cents, receipts_cents, receipt_ids, needs_confirmation, duplicate_ids}], 'unclaimed': [{receipt_id, status:'unclaimed_receipt', amount_cents}]}`;
  statuses: matched, amount_mismatch, missing_receipt, duplicate_receipt, total_mismatch (+ unclaimed_receipt).
- Store (`<data_dir>/claims.json`): `load_claims`, `upsert_claim(settings, claim, by='system')`, `set_state(settings, claim_id, state, by, date=None)`
  with STATES `received|needs_info|ready_to_approve|approved|paid`; `approved`/`paid` need a person's name (ValueError otherwise). `suggested_state(rec)` is never 'approved'.
- `committed_by_line(settings) -> {line_id: cents}` (approved, unpaid) -> pass as `pipeline.run(committed=...)`; shows as `committed_cents` in the report (not added to actual).
- Weekly: `weekly_summary(settings, recs, week_label)`, `claims_text(summary)` (guard-clean text; Claude may rephrase if `explain.number_guard(text, summary) == []`),
  `exception_email(claim, rec) -> {to, subject, body}`, `write_claims_excel(claims, recs, unclaimed, out_path)`.

## Step 14 `variance.emailing`
- Questions (`<data_dir>/questions/<Author>.json`, ids `ACE-Q-001`...): `create_questions(settings, author, profile, facts, explanation, date=None) -> [q]` (to owner via `owner_emails`, else `runner_email`),
  `list_questions(settings, status=None)` (status open|drafted|reply_received|answered), `draft_questions(client, settings, questions=None) -> [draft ids]` (subject `[ACE-Q-001] ...`),
  `collect_replies(client, settings, label=None) -> [reply]` (chosen label only; replies wait for review), `review_reply(settings, qid, msg_id, 'save_as_note'|'ignore', reviewer, txn_ids=(), date=None, edited_text=None)`,
  `answer_question(settings, qid, author, text, txn_ids, date=None) -> note` (typed answer; creates a coordinator note and closes the question).
- `draft_report(client, settings, paths, subject, body, to=None) -> draft_id`; `export_intake(client, settings, label=None)` context manager yielding `[{..., files}]` (.csv/.xlsx) for ingest, temp files deleted on exit.

## Step 15 `variance.scheduled` + `run_report.py`
- `python run_report.py path\to\job.yaml` (exit code 0/1). Job keys: name, profile, budget_file, actuals_file, period{label,start,end}, as_of_date?, backend template|api, redact?, stated_total_cents?, email_draft?.
- `run_job(job, settings=None, profiles=None, client=None, now=None, alerts_path=None) -> {ok, job, files, alerts[], backend_used, explanation}`; never raises. API without key falls back to template with an info alert.
- Alerts go to `user_data/alerts.md`; `read_alerts(path=None) -> [{when, job, status, items[]}]` newest first.
- `schtasks_command(job_path, name, when='08:00', day=1) -> str` is the command for the UI's Task Scheduler helper to show. Nothing is registered by the package.
