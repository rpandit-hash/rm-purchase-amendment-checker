"""
RM Purchase Amendment Checker
------------------------------
Streamlit frontend. Upload the raw GRN report -> app computes the correct
price-revision Amendment Amount per row using the authoritative Delta
Rate table (backend/rm_delta_rates.json), and rolls it up by supplier.
"""

import io
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from amendment_checker import (  # noqa: E402
    RATES_FILE,
    load_rate_table,
    get_current_rate,
    save_new_rate,
    pick_grn_sheet,
    find_and_read_header,
    process_grn_report,
    build_supplier_rollup,
)


def format_inr(value) -> str:
    """Format a number Indian-style (e.g. 31,27,230.38) with a rupee sign."""
    if value is None or pd.isna(value):
        return "-"
    negative = value < 0
    value = abs(value)
    whole, _, frac = f"{value:.2f}".partition(".")
    if len(whole) > 3:
        last3 = whole[-3:]
        rest = whole[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        whole = ",".join(groups) + "," + last3
    formatted = f"₹{whole}.{frac}"
    return f"-{formatted}" if negative else formatted

st.set_page_config(
    page_title="RM Purchase Amendment Checker",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
        [data-testid="stSidebar"] {display: none;}
        .block-container {padding-top: 2rem; padding-bottom: 3rem; max-width: 1200px;}

        .app-header {
            background: linear-gradient(135deg, #0f2843 0%, #1c4a72 100%);
            padding: 28px 32px;
            border-radius: 12px;
            margin-bottom: 28px;
        }
        .app-header h1 {
            color: #ffffff;
            font-size: 1.6rem;
            font-weight: 700;
            margin: 0 0 6px 0;
        }
        .app-header p {
            color: #cfe0ee;
            font-size: 0.92rem;
            margin: 0;
        }

        .kpi-card {
            background: #ffffff;
            border: 1px solid #e4e8ee;
            border-left: 4px solid #1c4a72;
            border-radius: 10px;
            padding: 16px 18px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }
        .kpi-card.flagged { border-left-color: #c0392b; }
        .kpi-card.flagged.ok { border-left-color: #2e8b57; }
        .kpi-label {
            font-size: 0.78rem;
            font-weight: 600;
            letter-spacing: 0.02em;
            color: #6b7280;
            text-transform: uppercase;
            margin-bottom: 6px;
        }
        .kpi-value {
            font-size: 1.5rem;
            font-weight: 700;
            color: #0f2843;
        }

        .section-title {
            font-size: 1.05rem;
            font-weight: 700;
            color: #0f2843;
            margin: 30px 0 12px 0;
            padding-bottom: 8px;
            border-bottom: 2px solid #e4e8ee;
        }

        div[data-testid="stFileUploader"] {
            border: 1px dashed #b7c3d0;
            border-radius: 10px;
            padding: 6px;
            background: #f8fafc;
        }
    </style>

    <div class="app-header">
        <h1>RM Purchase Amendment Checker</h1>
        <p>Upload the raw GRN report — amendment amounts are calculated from the backend
        delta-rate table, not a manually typed number.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---- Load rate table ----
try:
    rate_table = load_rate_table(RATES_FILE)
except Exception as e:
    st.error(f"Could not load rate table ({RATES_FILE}): {e}")
    st.stop()

import datetime as dt

with st.expander("Update Delta Rate"):
    st.caption("Change the CR / HR delta rate here when a new price revision comes in. "
               "No file editing needed — this updates automatically.")

    rate_col1, rate_col2 = st.columns(2)

    with rate_col1:
        st.markdown("**CR Rate**")
        current_cr = get_current_rate(rate_table, "CR")
        new_cr = st.number_input(
            "Current CR delta rate", min_value=0.0, value=float(current_cr or 0.0),
            step=0.001, format="%.3f", key="cr_rate_input",
        )
        cr_eff_date = st.date_input("Effective from", value=dt.date.today(), key="cr_eff_date")
        if st.button("Save CR Rate", key="save_cr"):
            save_new_rate("CR", new_cr, cr_eff_date)
            st.success(f"CR delta rate updated to {new_cr} (effective {cr_eff_date}).")
            st.rerun()

    with rate_col2:
        st.markdown("**HR Rate**")
        current_hr = get_current_rate(rate_table, "HR")
        new_hr = st.number_input(
            "Current HR delta rate", min_value=0.0, value=float(current_hr or 0.0),
            step=0.001, format="%.3f", key="hr_rate_input",
        )
        hr_eff_date = st.date_input("Effective from", value=dt.date.today(), key="hr_eff_date")
        if st.button("Save HR Rate", key="save_hr"):
            save_new_rate("HR", new_hr, hr_eff_date)
            st.success(f"HR delta rate updated to {new_hr} (effective {hr_eff_date}).")
            st.rerun()

# ---- File upload ----
uploaded = st.file_uploader("Upload GRN Report (.xlsx)", type=["xlsx"])

if uploaded is None:
    st.info("Upload a GRN report to begin.")
    st.stop()

try:
    sheet = pick_grn_sheet(uploaded)
except Exception as e:
    st.error(f"Could not read the uploaded file: {e}")
    st.stop()

# The GRN export has a few title/address rows above the real header row.
# Normal exports have headers on row 4 - try that first, and if the expected
# columns aren't there, silently auto-detect by scanning nearby rows instead
# of asking the user (this is an export-format detail, not a user decision).
try:
    df = find_and_read_header(uploaded, sheet)
except Exception as e:
    st.error(f"Could not parse the sheet: {e}")
    st.stop()

try:
    processed = process_grn_report(df, rate_table)
except ValueError as e:
    st.error(str(e))
    st.stop()

# ---- KPIs ----
total_amt = processed["Amendment Amt"].sum(skipna=True)
cr_amt = processed.loc[processed["Grade"] == "CR", "Amendment Amt"].sum(skipna=True)
hr_amt = processed.loc[processed["Grade"] == "HR", "Amendment Amt"].sum(skipna=True)
flagged_count = (processed["Flag"] != "").sum()

col1, col2, col3, col4 = st.columns(4)

def kpi_card(col, label, value, card_class=""):
    col.markdown(
        f"""
        <div class="kpi-card {card_class}">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

kpi_card(col1, "Total Amendment Amt", format_inr(total_amt))
kpi_card(col2, "CR Amendment Amt", format_inr(cr_amt))
kpi_card(col3, "HR Amendment Amt", format_inr(hr_amt))
kpi_card(
    col4, "Flagged Rows", int(flagged_count),
    card_class="flagged" if flagged_count else "flagged ok",
)

if flagged_count:
    st.warning(
        f"{flagged_count} row(s) could not be matched to a delta rate (date before earliest "
        "known quarter, unparseable date, or unknown category). Check the 'Flag' column below."
    )

# ---- Row-level detail ----
st.markdown('<div class="section-title">GRN Report</div>', unsafe_allow_html=True)

display_cols = [
    "PlantName", "SuppName", "GRN_No", "GRN_Date", "ItemGrade", "Grade",
    "ChallanQty", "Rate", "Delta Rate Used", "Amendment Amt", "Flag",
]
display_cols = [c for c in display_cols if c in processed.columns]

detail_display = processed[display_cols].copy()
for col in ("Rate", "Delta Rate Used", "Amendment Amt"):
    if col in detail_display.columns:
        detail_display[col] = detail_display[col].round(2)

def highlight_flags(row):
    return ["background-color: #ffe4e4" if row["Flag"] else "" for _ in row]

st.dataframe(
    detail_display.style.apply(highlight_flags, axis=1).format(
        {c: "{:.2f}" for c in ("Rate", "Delta Rate Used", "Amendment Amt") if c in detail_display.columns}
    ),
    use_container_width=True,
    height=420,
)

# ---- Supplier rollup ----
st.markdown('<div class="section-title">Summary</div>', unsafe_allow_html=True)
rollup = build_supplier_rollup(processed)
rollup_display = rollup.copy()
for col in ("CR Amt", "HR Amt", "HR + CR Amt"):
    if col in rollup_display.columns:
        rollup_display[col] = rollup_display[col].round(2)
st.dataframe(
    rollup_display.style.format(
        {c: "{:.2f}" for c in ("CR Amt", "HR Amt", "HR + CR Amt") if c in rollup_display.columns}
    ),
    use_container_width=True,
)

# ---- Export ----
st.markdown('<div class="section-title">Export</div>', unsafe_allow_html=True)

def to_excel_bytes(detail_df, rollup_df):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        detail_df.to_excel(writer, sheet_name="Row Detail", index=False)
        rollup_df.to_excel(writer, sheet_name="Supplier Rollup", index=False)
    buf.seek(0)
    return buf

excel_bytes = to_excel_bytes(processed[display_cols], rollup)
st.download_button(
    "Download results (.xlsx)",
    data=excel_bytes,
    file_name="rm_purchase_amendment_checked.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)