# RM Purchase Amendment Checker

Automates the manual pivot step of computing RM price-revision "Amendment
Amount" from the raw GRN report — replacing the old workflow where the
CR/HR delta rate was typed by hand into a pivot cell (and could go stale
or be mistyped, e.g. 1.45 instead of the correct 1.375).

## Structure

```
rm_amendment_checker/
  backend/
    amendment_checker.py   # core logic: rate lookup, row processing, rollup
    rm_delta_rates.json    # authoritative delta rate table (edit each quarter)
  frontend/
    app.py                 # Streamlit UI
```

## How it works

1. Upload the GRN report (raw row-level export, e.g. sheet "01.01 To 31.03").
2. For each row, the app looks up the Delta Rate by:
   - Category — the `Grade` column (CR / HR)
   - Quarter — whichever entry in `rm_delta_rates.json` has the latest
     `effective_from` on/before that row's `GRN_Date`
3. `Amendment Amt = ChallanQty x Delta Rate` per row.
4. Rows that don't match any rate (date earlier than the earliest known
   quarter, bad date, or unknown category) are flagged in red instead of
   silently guessed at.
5. A Supplier x Category rollup is shown underneath (same shape as the
   old manual pivot), plus KPI totals at the top.
6. Results can be downloaded as an .xlsx (row detail + rollup, two sheets).

## Updating rates each quarter

Whenever a new rate revision notice comes in (like the photographed RM
Steel Prices sheet), open `backend/rm_delta_rates.json` and append a new
entry under `CR` and `HR`:

```json
{
  "CR": [
    {"effective_from": "2026-01-01", "delta_rate": 1.375},
    {"effective_from": "2026-04-01", "delta_rate": 5.150}
  ],
  "HR": [
    {"effective_from": "2026-01-01", "delta_rate": 1.500},
    {"effective_from": "2026-04-01", "delta_rate": 5.500}
  ]
}
```

No code changes needed — the app always picks the entry whose
`effective_from` is the most recent one on/before each row's GRN_Date.

## Running

```
pip install streamlit pandas openpyxl
cd frontend
streamlit run app.py
```

## Notes / open items

- Rate lookup currently uses `GRN_Date` (not `InvoiceDate`) to decide the
  applicable quarter — flagged as tentative, easy to switch to
  `InvoiceDate` in `amendment_checker.py` (`process_grn_report`) if that
  turns out to be wrong once tested against more real data.
- Validated against `Summery_April_To_March.xlsx`: with delta rates set
  to 1.45 (CR) / 1.5 (HR) — matching the old manual pivot exactly — this
  tool reproduces the same Grand Total (3,169,652.55). With the corrected
  photo rates (1.375 / 1.5), the Grand Total becomes 3,127,230.38.
