# PRD completeness (Steps 1-15). Step 16 deferred by user. Test suite: 87 passed.

## Part A (backend)
- A-1.1 DONE - src/variance, tests, prompts, user_data, reports, pinned requirements.txt
- A-1.2 DONE - .gitignore; tests/test_inputs_unchanged.py (sha256 before/after)
- A-1.3 DONE - settings.py load_settings/save_settings, settings.template.yaml, .env
- A-2.1 DONE - ingest.py list_sheets/preview/guess_header_row/_table
- A-2.2 DONE - ingest.load_budget/load_actuals (normalized columns)
- A-2.3 DONE - mapping.py guess_mapping/save_profile/find_profile_by_fingerprint; sign + date_order
- A-2.4 DONE - budget layout total/monthly_wide/sections in mapping+ingest
- A-2.5 DONE - mapping.suggest_categories (difflib), save_category_map, UNBUDGETED lines
- A-3.1 DONE - calc.compute
- A-3.2 DONE - calc totals/rollups
- A-3.3 DONE - tests/test_calc.py
- A-4.1 DONE - facts.build_facts (redact option)
- A-4.2 DONE - explain.explain_template, paste (build_prompt/parse_pasted_reply), explain_api
- A-4.3 DONE - prompts/explain_system.md
- A-4.4 DONE - explain.number_guard
- A-5.1 DONE - reports.write_excel (source rows)
- A-5.2 DONE - reports.write_pdf (caveat, footer)
- A-6.1 DONE - pipeline.run
- A-6.2 DONE - required period, last_period saved
- A-6.3 DONE - as_of_date param
- A-7 DONE - calc timing/phasing/materiality/projection confidence/early_warning columns
- A-8 DONE - quality.run_checks, is_unreconciled
- A-9 DONE - drilldown.drill tags
- A-10 DONE - gmail.py (scopes, labels only, local token, account-problem help)
- A-11 DONE - reimburse.py (forms, OCR, reconcile, confidence, weekly, Excel, committed_by_line)
- A-12 DONE - notes.py per-author files, stale re-ask
- A-13 DONE - realloc.suggest, record_decision
- A-14 DONE - emailing.py (drafts, allow-list, ACE-Q ids, review_reply, export_intake)
- A-15 DONE - scheduled.py, run_report.py, alerts.md, schtasks_command
- A-16 DEFERRED BY USER

## Part B (frontend)
- B-1.1 DONE - run.bat, run.sh
- B-1.2 DONE - app.py sidebar flow + Settings
- B-1.3 DONE - README.md, HANDOVER.md
- B-2.1 DONE - ui/upload.py
- B-2.2 DONE - ui/mapping_ui.py _editor
- B-2.3 DONE - mapping_ui "Using saved mapping" + Change + picker
- B-2.4 DONE - mapping_ui _category_section
- B-2.5 DONE - friendly st.error across screens
- B-3.1 DONE - ui/check.py metrics
- B-3.2 DONE - check.py styled dataframe + legend
- B-3.3 DONE - check.py st.bar_chart
- B-4.1 DONE - check.py mode selector
- B-4.2 DONE - check.py paste flow (st.code copy)
- B-4.3 DONE - redact toggle
- B-4.4 DONE - rendered headline/issues/decisions in check.py
- B-5.1 DONE - ui/report.py downloads
- B-5.2 DONE - reports.write_pdf one page
- B-5.3 DONE - reports.write_excel freeze_panes, colors, Source row, Notes
- B-5.4 DONE - report.py Save to shared folder
- B-6 DONE - settings_ui.py, check.py period prefill, help/empty states
- B-7 DONE - check.py Timing and thresholds, CHIPS, confidence column
- B-8 DONE - ui/quality_ui.py, unreconciled banner
- B-9 DONE - check.py _drill
- B-10 DONE - ui/gmail_ui.py _connection (label multiselect, help)
- B-11 DONE - ui/claims_ui.py board, confirm w/ image, exceptions, weekly Excel, human-only approve
- B-12 DONE - ui/notes_ui.py
- B-13 DONE - ui/suggest_ui.py approve/dismiss/snooze
- B-14 DONE - gmail_ui.py _drafts (explicit Send), _inbox, _import
- B-15 DONE - ui/schedule_ui.py
- B-16 DEFERRED BY USER

Totals: Part A 25 DONE / 0 PARTIAL / 0 MISSING; Part B 28 DONE / 0 PARTIAL / 0 MISSING.
