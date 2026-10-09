# Budget & Variance Agent

Compares a budget file to an actuals export, flags the lines that are over or under, and writes a one-page PDF and an Excel detail file. The math is done by code. The plain-language explanation is a draft that you review. Nothing is sent or approved without you.

Your files are never changed. They are read in memory only.

## Install (once)

1. Install Python 3.11 or newer from https://www.python.org/downloads/ . On the first installer screen tick **Add python.exe to PATH**.
2. Get this folder onto your computer (copy or download it).

## Start the app

- Windows: double-click **run.bat**.
- Mac/Linux: run `./run.sh` in a terminal.

The first start takes a few minutes (it installs what it needs). After that it opens in seconds. Your browser opens the app. Keep the black window open while you work; close it to stop the app.

## The screens (left sidebar, top to bottom)

1. **Upload** - drop your budget file and your actuals export (CSV or Excel). For Excel pick the sheet. If there are notes above the column headings, set the "header row" to the row that holds the headings. The preview shows what the app sees.
2. **Map** - tell the app which column is which (it guesses). Answer the question about how expenses are shown (negative, positive, or debit/credit columns). If you used this budget before, the app says "Using saved mapping X" and you can change it. Then match the categories in your actuals to the categories in your budget. Suggestions are shown; anything you do not match is listed, never silently dropped. Your choices are saved for next time.
3. **Check** - enter the period (start and end date) and see the results: totals, a colored table of every line, and a bar chart. Red/amber lines are flagged. Then open the explanation: pick **Template** (no AI, always works), **Paste** (copy the prepared text into Claude yourself and paste the reply back), or **API** (only if a key has been set up). Every figure in an explanation is checked against the computed numbers; anything that does not match is shown and rejected.
4. **Report** - make the PDF one-pager and the Excel detail and download them, or save them to the shared folder.
5. **Settings** - period dates, flag thresholds (default: over $150 and over 10%), shared folder.

Use **Redact descriptions** when you do not want transaction descriptions included in what is sent for the explanation.

## Where do reports go?

Downloaded files go to your browser's Downloads folder. "Save to shared folder" writes to the folder set in Settings. The app's own copy is in the `reports` folder next to this file. Your saved mappings are in `user_data`. Neither is shared through the code repository.

## If something goes wrong

- A red message names the column or sheet it could not read. Fix it on the Upload or Map screen.
- "Ambiguous dates": the app will not guess 03/04/2026. Choose the date order on the Map screen.
- Anything else: send the person who handed this tool to you the message you saw (see HANDOVER.md).
