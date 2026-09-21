# RM Purchase Amendment Checker

Automates the manual pivot step of computing RM price-revision "Amendment
Amount" from the raw GRN report — replacing the old workflow where the
CR/HR delta rate was typed by hand into a pivot cell (and could go stale
or be mistyped, e.g. 1.45 instead of the correct 1.375).

## Structure

```
rm_amendment_checker/
  Start_Dashboard.bat     # double-click this to run the app (no terminal needed)
  requirements.txt
  backend/
    amendment_checker.py   # core logic: rate lookup, row processing, rollup
    rm_delta_rates.json      # current CR/HR delta rate — edit via the dashboard, not by hand
  frontend/
    amendment.py             # Streamlit UI
```

## How it works

1. Upload the GRN report (raw row-level export from Cloud9 ERP — the app
   auto-detects the correct sheet and header row, no manual selection needed).
2. For each row, the app looks up the Delta Rate purely by **Category**
   (the `Grade` column — CR or HR). There is one current rate per
   category — no dates, no quarters.
3. `Amendment Amt = ChallanQty x Delta Rate` per row.
4. Rows with an unrecognized category are flagged in red instead of
   silently guessed at.
5. A Supplier x Category rollup ("Summary") is shown underneath (same
   shape as the old manual pivot), plus KPI totals at the top, formatted
   in Indian currency style (e.g. ₹31,27,230.38).
6. Results can be downloaded as an .xlsx (row detail + rollup, two sheets).

## Updating the rate

No file editing, no JSON, no Notepad. On the dashboard, open **"Update
Delta Rate"**, type the new CR and/or HR rate, click Save.

- The change applies **immediately and retroactively** — every row in
  every report uploaded from then on recalculates with the new rate,
  regardless of the row's date. There is no history; the newest saved
  value is simply "the" rate.
- Under the hood this writes straight to `backend/rm_delta_rates.json`
  (flat shape: `{"CR": {"delta_rate": ..., "grades": [...]}, "HR": {...}}`),
  so the change is permanent (survives closing/reopening the app) until
  changed again.
- `grades` in the JSON is documentation only (which grades the rate
  covers, per the official price-revision notice) — it is not used in
  the calculation, which keys off the GRN sheet's CR/HR `Grade` column
  directly.

## Running

**For a non-technical user (e.g. on someone else's laptop):**
Double-click `Start_Dashboard.bat`. First run sets up a local Python
environment automatically (one-time, ~1-2 min); every run after that
starts in a few seconds and opens the dashboard in the browser. Requires
Python to be installed on that machine (the .bat will say so clearly and
link to python.org if it's missing) — if Python is installed but not on
PATH, the .bat also checks common install locations automatically.

**Manually (for development):**
```
pip install streamlit pandas openpyxl
cd frontend
streamlit run amendment.py
```

## Notes / open items

- The date-based "which quarter's rate applies" logic (an earlier
  version keyed rates by `effective_from` + `GRN_Date`) was intentionally
  removed — the tool now always uses whatever rate is currently saved,
  applied uniformly to all rows regardless of date. If historical
  accuracy per quarter is ever needed again, that logic can be
  reinstated in `amendment_checker.py`.
- Validated against `Summery_April_To_March.xlsx`: with delta rates set
  to 1.45 (CR) / 1.5 (HR) — matching the old manual pivot exactly — this
  tool reproduced the same Grand Total (3,169,652.55). With the corrected
  rates (1.375 / 1.5), the Grand Total becomes 3,127,230.38.
- If the dashboard ever shows stale results after a file update, fully
  close the terminal window running it and reopen via
  `Start_Dashboard.bat` — Streamlit hot-reloads the page but not always
  every imported backend module.
