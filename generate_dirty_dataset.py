"""
generate_dirty_dataset.py
=========================
Generates a completely synthetic, intentionally corrupted corporate dataset
from scratch. No files are read from disk. Outputs synthetic_corrupted_data.csv
at the project root.

Run: python generate_dirty_dataset.py
"""

import random
import string
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 0. SEED FOR REPRODUCIBILITY
# ---------------------------------------------------------------------------

RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

BASE_ROWS = 500
OUTPUT_PATH = "synthetic_corrupted_data.csv"

# ---------------------------------------------------------------------------
# 1. RAW DATA GENERATION — baseline clean synthetic data
# ---------------------------------------------------------------------------

print("=" * 60)
print("  BIFlow — Synthetic Dirty Dataset Generator")
print("=" * 60)
print(f"\n[1/4] Generating {BASE_ROWS} baseline synthetic rows...")

# --- Transaction IDs --------------------------------------------------------
transaction_ids = [f"TXN-{str(i).zfill(5)}" for i in range(1, BASE_ROWS + 1)]

# --- Customer Names (fake first + last name combinations) -------------------
first_names = [
    "Alice", "Bob", "Carlos", "Diana", "Ethan", "Fatima", "George", "Hannah",
    "Ivan", "Julia", "Kevin", "Laura", "Mohammed", "Nina", "Oscar", "Priya",
    "Quentin", "Rachel", "Samuel", "Tina", "Umar", "Vera", "William", "Xena",
    "Yusuf", "Zoe",
]
last_names = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Martinez", "Hernandez", "Lopez", "Wilson", "Anderson", "Thomas",
    "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White",
    "Harris", "Sanchez", "Clark", "Ramirez",
]
customer_names = [
    f"{random.choice(first_names)} {random.choice(last_names)}"
    for _ in range(BASE_ROWS)
]

# --- Join Dates (random dates between 2018-01-01 and 2024-12-31) ------------
start_date = datetime(2018, 1, 1)
date_range_days = (datetime(2024, 12, 31) - start_date).days

join_dates = [
    (start_date + timedelta(days=random.randint(0, date_range_days))).strftime("%Y-%m-%d")
    for _ in range(BASE_ROWS)
]

# --- Amount USD (realistic transaction amounts between $10 and $9,500) ------
amounts = [round(random.uniform(10.0, 9500.0), 2) for _ in range(BASE_ROWS)]

# --- Status (clean baseline values) ----------------------------------------
clean_statuses = ["Active", "Inactive", "Pending", "Cancelled", "Completed"]
statuses = [random.choice(clean_statuses) for _ in range(BASE_ROWS)]

# Assemble clean DataFrame
df = pd.DataFrame(
    {
        "Transaction_ID": transaction_ids,
        "Customer_Name": customer_names,
        "Join_Date": join_dates,
        "Amount_USD": amounts,
        "Status": statuses,
    }
)

print(f"    ✓ Baseline DataFrame created: {df.shape[0]} rows × {df.shape[1]} columns")

# ---------------------------------------------------------------------------
# 2. CORRUPTION INJECTION
# ---------------------------------------------------------------------------

print("\n[2/4] Injecting data quality anomalies...")

# ---------------------------------------------------------------------------
# 2a. MISSING VALUES — 15% of Amount_USD and Join_Date forced to NaN
# ---------------------------------------------------------------------------

missing_target_pct = 0.15
n_missing = int(BASE_ROWS * missing_target_pct)  # 75 rows each

amount_null_indices = random.sample(range(BASE_ROWS), n_missing)
date_null_indices = random.sample(range(BASE_ROWS), n_missing)

df.loc[amount_null_indices, "Amount_USD"] = np.nan
df.loc[date_null_indices, "Join_Date"] = np.nan

print(f"    ✓ Missing values injected: {n_missing} nulls in 'Amount_USD', "
      f"{n_missing} nulls in 'Join_Date'")

# ---------------------------------------------------------------------------
# 2b. INVALID DATA TYPES — 10% of Amount_USD rows injected with broken strings
#     (only into rows that are NOT already NaN to keep anomalies distinct)
# ---------------------------------------------------------------------------

invalid_strings = [
    "ERROR_404",
    "CANCELLED_$",
    "N/A",
    "##CORRUPT##",
    "NULL_VAL",
    "---",
    "UNKNOWN",
    "BAD_DATA",
    "OVERFLOW_ERR",
    "!INVALID!",
]

# Candidate rows: Amount_USD is currently NaN → skip those, inject into non-null
non_null_amount_indices = df[df["Amount_USD"].notna()].index.tolist()
n_type_errors = int(BASE_ROWS * 0.10)  # 50 rows
type_error_indices = random.sample(non_null_amount_indices, n_type_errors)

# Convert column to object dtype before injecting strings
df["Amount_USD"] = df["Amount_USD"].astype(object)
for idx in type_error_indices:
    df.at[idx, "Amount_USD"] = random.choice(invalid_strings)

print(f"    ✓ Invalid type strings injected: {n_type_errors} rows in 'Amount_USD'")

# ---------------------------------------------------------------------------
# 2c. WHITESPACE & CASING ANOMALIES — dirty Status values
# ---------------------------------------------------------------------------

dirty_status_variants = [
    " Active ",
    " active",
    "active ",
    "ACTIVE",
    " Inactive ",
    "inactive",
    "INACTIVE ",
    " Pending",
    "PENDING ",
    "pending ",
    " Cancelled",
    "CANCELLED",
    " cancelled ",
    "Completed ",
    " completed",
    "COMPLETED",
    "  Active  ",
    " PENDING",
    "Inactive ",
    " Active",
]

# Inject dirty casing/whitespace into every Status row (full column corruption)
df["Status"] = [random.choice(dirty_status_variants) for _ in range(len(df))]

print(f"    ✓ Whitespace/casing anomalies injected: all {len(df)} rows in 'Status'")

# ---------------------------------------------------------------------------
# 2d. STRUCTURAL DUPLICATES — duplicate exactly 40 random rows
# ---------------------------------------------------------------------------

N_DUPLICATES = 40
duplicate_source_indices = random.sample(range(BASE_ROWS), N_DUPLICATES)
duplicate_rows = df.iloc[duplicate_source_indices].copy()

df = pd.concat([df, duplicate_rows], ignore_index=True)

print(f"    ✓ Structural duplicates injected: {N_DUPLICATES} duplicate rows appended")

# ---------------------------------------------------------------------------
# 3. SAVE TO DISK
# ---------------------------------------------------------------------------

print(f"\n[3/4] Saving corrupted dataset to '{OUTPUT_PATH}'...")

df.to_csv(OUTPUT_PATH, index=False)

print(f"    ✓ File saved successfully.")

# ---------------------------------------------------------------------------
# 4. CONSOLE SUMMARY REPORT
# ---------------------------------------------------------------------------

print("\n[4/4] Computing anomaly audit summary...\n")

total_rows, total_cols = df.shape

# Recount actual anomalies in the saved frame
actual_amount_nulls = df["Amount_USD"].isna().sum()
actual_date_nulls = df["Join_Date"].isna().sum()

# Type errors: non-null Amount_USD values that cannot be cast to float
def is_numeric_string(val):
    try:
        float(val)
        return False
    except (TypeError, ValueError):
        return True

actual_type_errors = df["Amount_USD"].dropna().apply(is_numeric_string).sum()

actual_duplicates = int(df.duplicated().sum())

# Whitespace anomalies: Status values that differ from their stripped+title form
actual_whitespace = df["Status"].apply(
    lambda x: str(x) != str(x).strip().title()
).sum()

print("=" * 60)
print("  SYNTHETIC CORRUPTED DATASET — ANOMALY AUDIT")
print("=" * 60)
print(f"  Output file      : {OUTPUT_PATH}")
print(f"  Final dimensions : {total_rows} rows × {total_cols} columns")
print(f"  Base rows        : {BASE_ROWS}")
print(f"  Appended dupes   : {N_DUPLICATES}")
print("-" * 60)
print(f"  NULL — Amount_USD   : {actual_amount_nulls} cells  "
      f"({actual_amount_nulls / total_rows * 100:.1f}%)")
print(f"  NULL — Join_Date    : {actual_date_nulls} cells  "
      f"({actual_date_nulls / total_rows * 100:.1f}%)")
print(f"  TYPE ERRORS         : {actual_type_errors} cells  "
      f"({actual_type_errors / total_rows * 100:.1f}%)")
print(f"  DUPLICATES          : {actual_duplicates} rows")
print(f"  WHITESPACE/CASING   : {actual_whitespace} cells  "
      f"({actual_whitespace / total_rows * 100:.1f}%)")
print("-" * 60)
total_anomalies = (
    int(actual_amount_nulls)
    + int(actual_date_nulls)
    + int(actual_type_errors)
    + actual_duplicates
    + int(actual_whitespace)
)
print(f"  TOTAL ANOMALIES     : {total_anomalies}")
print("=" * 60)
print("\n  Dataset is ready to stress-test the agent pipeline.\n")
