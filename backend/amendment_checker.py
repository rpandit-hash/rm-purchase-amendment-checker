"""
RM Purchase Amendment Checker - Backend Logic
------------------------------------------------
Reads a GRN report (raw, row-level export from Cloud9 ERP) and computes
the RM price-revision "Amendment Amount" for every row, using a single
current Delta Rate per category (CR / HR) instead of a manually typed
pivot number.

Rule:
    Amendment Amt (row) = ChallanQty x Delta Rate

    Delta Rate is looked up purely by Category (from the row's 'Grade'
    column: CR or HR). There is one current rate per category - when it's
    changed, it applies to every row, regardless of date.
"""

import json
import os

import pandas as pd

RATES_FILE = os.path.join(os.path.dirname(__file__), "rm_delta_rates.json")

REQUIRED_COLUMNS = [
    "PlantName", "SuppCode", "SuppName", "GRN_No", "GRN_Date",
    "InvoiceNo", "InvoiceDate", "ItemNo", "ItemDesc", "ItemGrade",
    "ChallanQty", "Rate", "SubTotal", "Total", "Grade",
]


def load_rate_table(path: str = RATES_FILE) -> dict:
    """Load the delta-rate JSON config. Shape: {"CR": {"delta_rate": 1.375, "grades": [...]}, "HR": {...}}"""
    with open(path, "r") as f:
        raw = json.load(f)

    table = {}
    for category, entry in raw.items():
        table[category.upper()] = {
            "delta_rate": float(entry["delta_rate"]),
            "grades": entry.get("grades", []),  # documentation only, not used in lookup
        }
    return table


def get_current_rate(rate_table: dict, category: str):
    """Return the current delta rate for a category, or None."""
    entry = rate_table.get(str(category).upper())
    return entry["delta_rate"] if entry else None


def save_new_rate(category: str, new_delta_rate: float, path: str = RATES_FILE) -> None:
    """Update the current delta rate for a category and write it back to rm_delta_rates.json."""
    category = str(category).upper()
    with open(path, "r") as f:
        raw = json.load(f)

    raw.setdefault(category, {"grades": []})
    raw[category]["delta_rate"] = float(new_delta_rate)

    with open(path, "w") as f:
        json.dump(raw, f, indent=2)


def find_delta_rate(rate_table: dict, category: str):
    """Return the current delta rate for a category, or None if the category is unknown."""
    entry = rate_table.get(str(category).upper())
    return entry["delta_rate"] if entry else None


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
        - Delta Rate Used
        - Amendment Amt
        - Flag (blank, or reason string if the category is unrecognized)
    """
    df = df.copy()

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"GRN report is missing expected column(s): {missing}")

    delta_rates = []
    flags = []

    for _, row in df.iterrows():
        category = row["Grade"]

        if str(category).upper() not in ("CR", "HR"):
            delta_rates.append(None)
            flags.append(f"Unknown category '{category}'")
            continue

        rate = find_delta_rate(rate_table, category)
        delta_rates.append(rate)
        flags.append("" if rate is not None else "No rate found for this category")

    df["Delta Rate Used"] = delta_rates
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