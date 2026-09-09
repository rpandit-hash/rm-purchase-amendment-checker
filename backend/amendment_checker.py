"""
RM Purchase Amendment Checker - Backend Logic
------------------------------------------------
Reads a GRN report (raw, row-level export from Cloud9 ERP) and computes
the correct RM price-revision "Amendment Amount" for every row, using an
authoritative Delta Rate table (rm_delta_rates.json) instead of a
manually typed pivot number.

Rule:
    Amendment Amt (row) = ChallanQty x Delta Rate

    Delta Rate is looked up by:
        1. Category  -> from the 'Grade' column (CR / HR)
        2. Quarter    -> the rate entry with the latest 'effective_from'
                         that is <= the row's GRN_Date

If no rate entry qualifies for a row's date (i.e. GRN_Date is earlier
than the earliest known effective_from for that category), the row is
flagged instead of guessed at.
"""

import json
import os
from datetime import datetime

import pandas as pd

RATES_FILE = os.path.join(os.path.dirname(__file__), "rm_delta_rates.json")

REQUIRED_COLUMNS = [
    "PlantName", "SuppCode", "SuppName", "GRN_No", "GRN_Date",
    "InvoiceNo", "InvoiceDate", "ItemNo", "ItemDesc", "ItemGrade",
    "ChallanQty", "Rate", "SubTotal", "Total", "Grade",
]

DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d")


def load_rate_table(path: str = RATES_FILE) -> dict:
    """Load and lightly validate the delta-rate JSON config."""
    with open(path, "r") as f:
        raw = json.load(f)

    table = {}
    for category, entries in raw.items():
        parsed = []
        for e in entries:
            parsed.append({
                "effective_from": datetime.strptime(e["effective_from"], "%Y-%m-%d"),
                "delta_rate": float(e["delta_rate"]),
                "grades": e.get("grades", []),  # documentation only, not used in lookup
            })
        parsed.sort(key=lambda x: x["effective_from"])
        table[category.upper()] = parsed
    return table


def _parse_date(value):
    if isinstance(value, datetime):
        return value
    if pd.isna(value):
        return None
    s = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # last resort: let pandas try
    try:
        return pd.to_datetime(s, dayfirst=True).to_pydatetime()
    except Exception:
        return None


def find_delta_rate(rate_table: dict, category: str, grn_date: datetime):
    """Return (delta_rate, effective_from) for the applicable quarter, or (None, None)."""
    entries = rate_table.get(str(category).upper())
    if not entries or grn_date is None:
        return None, None

    applicable = [e for e in entries if e["effective_from"] <= grn_date]
    if not applicable:
        return None, None

    best = max(applicable, key=lambda e: e["effective_from"])
    return best["delta_rate"], best["effective_from"]


DEFAULT_HEADER_ROW = 4  # 1-indexed; GRN exports have 3 title/address rows above the headers
HEADER_SCAN_RANGE = range(1, 11)  # fall back to scanning rows 1-10 if the default doesn't match


def pick_grn_sheet(file) -> str:
    """
    Pick the raw GRN data sheet automatically instead of asking the user.
    Rule: skip any sheet whose name looks like a summary/pivot sheet
    (contains 'summ'); among the rest, prefer the one whose header row
    (found via find_and_read_header) actually matches the expected GRN
    columns. Falls back to the only sheet if there's just one.
    """
    xls = pd.ExcelFile(file)
    sheet_names = xls.sheet_names

    if len(sheet_names) == 1:
        return sheet_names[0]

    candidates = [s for s in sheet_names if "summ" not in s.lower()] or sheet_names

    for name in candidates:
        try:
            find_and_read_header(file, name)
            return name
        except Exception:
            continue

    # Nothing matched cleanly - just go with the best guess.
    return candidates[0]


def find_and_read_header(file, sheet_name: str) -> pd.DataFrame:
    """
    Read a GRN export sheet without asking the user which row the headers
    are on. Tries the standard row first (DEFAULT_HEADER_ROW); if the
    expected columns aren't found there, scans nearby rows for the real
    header row instead.
    """
    # Fast path: the standard export layout.
    df = pd.read_excel(file, sheet_name=sheet_name, header=DEFAULT_HEADER_ROW - 1)
    df = df.dropna(how="all")
    if all(c in df.columns for c in REQUIRED_COLUMNS):
        return df

    # Fallback: scan a handful of rows near the top for one that matches
    # the expected column names.
    for row_num in HEADER_SCAN_RANGE:
        candidate = pd.read_excel(file, sheet_name=sheet_name, header=row_num - 1)
        candidate = candidate.dropna(how="all")
        if all(c in candidate.columns for c in REQUIRED_COLUMNS):
            return candidate

    raise ValueError(
        "Could not automatically find the header row (expected columns like "
        f"{REQUIRED_COLUMNS[:4]}...). The sheet's layout may have changed."
    )


def process_grn_report(df: pd.DataFrame, rate_table: dict) -> pd.DataFrame:
    """
    Take a raw GRN dataframe and append:
        - GRN_Date_Parsed
        - Delta Rate Used
        - Rate Effective From
        - Amendment Amt
        - Flag (blank, or reason string if something's off)
    """
    df = df.copy()

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"GRN report is missing expected column(s): {missing}")

    parsed_dates = df["GRN_Date"].apply(_parse_date)
    df["GRN_Date_Parsed"] = parsed_dates

    delta_rates = []
    eff_froms = []
    flags = []

    for _, row in df.iterrows():
        category = row["Grade"]
        grn_date = row["GRN_Date_Parsed"]

        if grn_date is None:
            delta_rates.append(None)
            eff_froms.append(None)
            flags.append("Unparseable GRN_Date")
            continue

        if str(category).upper() not in ("CR", "HR"):
            delta_rates.append(None)
            eff_froms.append(None)
            flags.append(f"Unknown category '{category}'")
            continue

        rate, eff_from = find_delta_rate(rate_table, category, grn_date)
        delta_rates.append(rate)
        eff_froms.append(eff_from)
        flags.append("" if rate is not None else "No rate found for this date")

    df["Delta Rate Used"] = delta_rates
    df["Rate Effective From"] = eff_froms
    df["Amendment Amt"] = df.apply(
        lambda r: round(r["ChallanQty"] * r["Delta Rate Used"], 2)
        if pd.notna(r["Delta Rate Used"]) else None,
        axis=1,
    )
    df["Flag"] = flags

    return df


def build_supplier_rollup(processed_df: pd.DataFrame) -> pd.DataFrame:
    """
    Supplier x Category rollup (replaces the old manual pivot):
    Qty CR, Qty HR, Qty Grand Total, CR Amt, HR Amt, HR+CR Amt
    """
    df = processed_df.copy()

    qty_pivot = pd.pivot_table(
        df, index="SuppName", columns="Grade", values="ChallanQty",
        aggfunc="sum", fill_value=0,
    )
    amt_pivot = pd.pivot_table(
        df, index="SuppName", columns="Grade", values="Amendment Amt",
        aggfunc="sum", fill_value=0,
    )

    for col in ("CR", "HR"):
        if col not in qty_pivot.columns:
            qty_pivot[col] = 0
        if col not in amt_pivot.columns:
            amt_pivot[col] = 0

    rollup = pd.DataFrame({
        "SuppName": qty_pivot.index,
        "Qty CR": qty_pivot["CR"].values,
        "Qty HR": qty_pivot["HR"].values,
        "CR Amt": amt_pivot["CR"].values,
        "HR Amt": amt_pivot["HR"].values,
    })
    rollup["Qty Grand Total"] = rollup["Qty CR"] + rollup["Qty HR"]
    rollup["HR + CR Amt"] = rollup["CR Amt"] + rollup["HR Amt"]

    grand_total = {
        "SuppName": "Grand Total",
        "Qty CR": rollup["Qty CR"].sum(),
        "Qty HR": rollup["Qty HR"].sum(),
        "CR Amt": rollup["CR Amt"].sum(),
        "HR Amt": rollup["HR Amt"].sum(),
        "Qty Grand Total": rollup["Qty Grand Total"].sum(),
        "HR + CR Amt": rollup["HR + CR Amt"].sum(),
    }
    rollup = pd.concat([rollup, pd.DataFrame([grand_total])], ignore_index=True)

    cols = ["SuppName", "Qty CR", "Qty HR", "Qty Grand Total", "CR Amt", "HR Amt", "HR + CR Amt"]
    return rollup[cols]
