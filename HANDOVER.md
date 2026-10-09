# Handover

Fill this in when passing the tool to a new coordinator.

| Item | Value |
|---|---|
| Owner / contact | |
| Budget this profile covers | |
| Saved mapping profile name | |
| Shared folder path | |
| Period convention (e.g. fiscal year start) | |
| Date handed over | |
| Gmail account / labels used | |
| Reimbursement label and claim form layout | |
| Scheduled job names | |

## Checklist for the new coordinator
- [ ] Python 3.11+ installed, run.bat starts the app
- [ ] Ran one report from README alone
- [ ] Mapping profile for my budget saved
- [ ] Shared folder set in Settings and a test save worked
- [ ] Know that the explanation is a draft and that you approve everything

## Known quirks of this budget
(List odd categories, merged rows, sign conventions, months to ignore.)

## Open questions / decisions pending

## For the next developer
- Screens live in `ui/` (one file each); they only call functions in `src/variance`. Backend interface notes: `src/variance/CONTRACT.md`.
- UI tests: `python -m pytest ui_tests` (headless, in-memory data, temp folders, fake Gmail).
- The question email body preview in `ui/gmail_ui.py` (`_question_body`) mirrors `emailing.draft_questions`; keep them in step.
- Receipts and their images live in session memory only; claims are stored in `claims.json` in the data folder.
