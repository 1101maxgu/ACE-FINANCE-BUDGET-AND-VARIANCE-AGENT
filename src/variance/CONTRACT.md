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
