#!/usr/bin/env python3
"""
fetch_storm_data.py
-------------------
Downloads NOAA Storm Events CSVs for 2020–2026, filters for tornado,
hail, and damaging wind events, aggregates by state/month, normalizes
by state area, and writes two output files:

  storm_data.js   — paste this into your React app to replace the
                    fake LTA_BASE / generateYearData data
  storm_data.json — raw numbers if you want to inspect them

Run from your project folder:
    cd /Users/stevejaye/Documents/vibe_apps/SevereStorm_Comparison
    pip install requests pandas
    python fetch_storm_data.py
"""

import os
import io
import json
import requests
import zipfile
import pandas as pd

# ── Configuration ──────────────────────────────────────────────────────────────

OUTPUT_DIR   = os.path.dirname(os.path.abspath(__file__))
YEARS        = list(range(1991, 2027))   # 1991 – 2026 (full LTA range)
CACHE_DIR    = os.path.join(OUTPUT_DIR, "_cache")
BASE_URL     = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"

# NOAA event type strings we care about
EVENT_MAP = {
    "Tornado":            "tornado",
    "Hail":               "hail",
    "Thunderstorm Wind":  "wind",
}

# State areas in square miles (for normalising to events / 10k sq mi)
STATE_AREA_SQMI = {
    "AL":52420,"AR":53179,"AZ":113990,"CA":163696,"CO":104094,
    "CT":5543, "DE":2489, "FL":65758, "GA":59425, "IA":56273,
    "ID":83569,"IL":57914,"IN":36420, "KS":82278, "KY":40408,
    "LA":52378,"MA":10554,"MD":12407, "ME":35380, "MI":96714,
    "MN":86936,"MO":69707,"MS":48432, "MT":147040,"NC":53819,
    "ND":70698,"NE":77358,"NH":9349,  "NJ":8723,  "NM":121590,
    "NV":110572,"NY":54555,"OH":44826,"OK":69899, "OR":98379,
    "PA":46054,"RI":1545, "SC":32020, "SD":77116, "TN":42144,
    "TX":268596,"UT":84897,"VA":42775,"VT":9616,  "WA":71298,
    "WI":65496,"WV":24230,"WY":97813,
}

# Only these states have data in LTA_BASE — match the app
APP_STATES = [
    "AL","AR","AZ","CA","CO","CT","DE","FL","GA","IA","ID","IL","IN","KS","KY",
    "LA","MA","MD","ME","MI","MN","MO","MS","MT","NC","ND","NE","NH","NJ","NM",
    "NV","NY","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VA","VT","WA","WI",
    "WV","WY"
]

os.makedirs(CACHE_DIR, exist_ok=True)

# ── Helpers ────────────────────────────────────────────────────────────────────

def find_detail_filename(year):
    """
    NOAA filenames look like:
      StormEvents_details-ftp_v1.0_d2024_c20250317.csv.gz
    We hit the index page and find the right one.
    """
    print(f"  Checking index for year {year}...")
    resp = requests.get(BASE_URL, timeout=30)
    resp.raise_for_status()
    for line in resp.text.splitlines():
        if f"_details-ftp_v1.0_d{year}_" in line and ".csv.gz" in line:
            # Extract filename from href
            start = line.find('href="') + 6
            end   = line.find('"', start)
            return line[start:end]
    return None


def download_and_cache(year):
    cache_path = os.path.join(CACHE_DIR, f"details_{year}.csv")
    if os.path.exists(cache_path):
        print(f"  [{year}] Using cached file.")
        return cache_path

    filename = find_detail_filename(year)
    if not filename:
        print(f"  [{year}] WARNING: No detail file found on NOAA server — skipping.")
        return None

    url = BASE_URL + filename
    print(f"  [{year}] Downloading {filename}...")
    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()

    # File is .csv.gz — decompress in memory
    import gzip
    with gzip.open(io.BytesIO(resp.content), "rt", encoding="latin-1") as gz:
        content = gz.read()

    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  [{year}] Saved to cache.")
    return cache_path


def load_year(year):
    path = download_and_cache(year)
    if path is None:
        return None

    df = pd.read_csv(path, low_memory=False, encoding="utf-8")

    # Normalise column names (NOAA sometimes changes capitalisation)
    df.columns = [c.strip().upper() for c in df.columns]

    # Keep only columns we need
    needed = ["STATE_FIPS", "STATE", "EVENT_TYPE", "MONTH_NAME", "BEGIN_DATE_TIME"]
    # Some years use slightly different column names
    col_map = {}
    for col in df.columns:
        for n in needed:
            if col == n or col.replace(" ","_") == n:
                col_map[n] = col
    df = df.rename(columns={v: k for k, v in col_map.items()})

    # Filter to event types we want
    df = df[df["EVENT_TYPE"].isin(EVENT_MAP.keys())].copy()
    df["hazard"] = df["EVENT_TYPE"].map(EVENT_MAP)

    # Parse month number from MONTH_NAME (e.g. "March" → 3)
    month_nums = {
        "January":1,"February":2,"March":3,"April":4,"May":5,"June":6,
        "July":7,"August":8,"September":9,"October":10,"November":11,"December":12
    }
    df["month"] = df["MONTH_NAME"].map(month_nums)
    df = df.dropna(subset=["month"])
    df["month"] = df["month"].astype(int)

    # Map NOAA state name → abbreviation
    df["state_abbr"] = df["STATE"].str.strip().str.upper().map(STATE_NAME_TO_ABBR)
    df = df[df["state_abbr"].isin(APP_STATES)]

    return df


# NOAA uses full state names in the STATE column
STATE_NAME_TO_ABBR = {
    "ALABAMA":"AL","ALASKA":"AK","ARIZONA":"AZ","ARKANSAS":"AR","CALIFORNIA":"CA",
    "COLORADO":"CO","CONNECTICUT":"CT","DELAWARE":"DE","FLORIDA":"FL","GEORGIA":"GA",
    "HAWAII":"HI","IDAHO":"ID","ILLINOIS":"IL","INDIANA":"IN","IOWA":"IA",
    "KANSAS":"KS","KENTUCKY":"KY","LOUISIANA":"LA","MAINE":"ME","MARYLAND":"MD",
    "MASSACHUSETTS":"MA","MICHIGAN":"MI","MINNESOTA":"MN","MISSISSIPPI":"MS",
    "MISSOURI":"MO","MONTANA":"MT","NEBRASKA":"NE","NEVADA":"NV","NEW HAMPSHIRE":"NH",
    "NEW JERSEY":"NJ","NEW MEXICO":"NM","NEW YORK":"NY","NORTH CAROLINA":"NC",
    "NORTH DAKOTA":"ND","OHIO":"OH","OKLAHOMA":"OK","OREGON":"OR","PENNSYLVANIA":"PA",
    "RHODE ISLAND":"RI","SOUTH CAROLINA":"SC","SOUTH DAKOTA":"SD","TENNESSEE":"TN",
    "TEXAS":"TX","UTAH":"UT","VERMONT":"VT","VIRGINIA":"VA","WASHINGTON":"WA",
    "WEST VIRGINIA":"WV","WISCONSIN":"WI","WYOMING":"WY",
    # NOAA sometimes writes these with "Lake" prefix
    "LAKE ST. CLAIR":"MI","LAKE MICHIGAN":"IL",
}


# ── Main processing ────────────────────────────────────────────────────────────

print("=" * 60)
print("NOAA Storm Events Data Fetcher")
print("=" * 60)

# Structure: { year: { hazard: { state: [m1..m12] } } }
# and:       { "lta": { hazard: { state: [m1..m12] } } }
all_data   = {}   # year → hazard → state → [12 monthly counts]
lta_counts = {}   # for computing 30-yr LTA we'll use 2020-2024 (what we have)

for year in YEARS:
    print(f"\nProcessing {year}...")
    df = load_year(year)
    if df is None:
        print(f"  Skipping {year} (no data available yet).")
        continue

    year_data = {}
    for hazard in ["tornado", "hail", "wind"]:
        haz_df = df[df["hazard"] == hazard]
        state_data = {}
        for state in APP_STATES:
            area_10k = STATE_AREA_SQMI.get(state, 50000) / 10000
            monthly = []
            for m in range(1, 13):
                count = len(haz_df[
                    (haz_df["state_abbr"] == state) &
                    (haz_df["month"] == m)
                ])
                # Normalise to events per 10,000 sq mi, round to 1dp
                monthly.append(round(count / area_10k, 1))
            state_data[state] = monthly
        year_data[hazard] = state_data

    all_data[year] = year_data
    print(f"  Done — {len(df)} events processed.")


# ── Compute LTA from available completed years ────────────────────────────────
print("\nComputing LTA from available years...")
completed_years = [y for y in YEARS if y in all_data and y < 2025]

lta = {}
for hazard in ["tornado", "hail", "wind"]:
    lta[hazard] = {}
    for state in APP_STATES:
        monthly_lta = []
        for m in range(12):
            vals = [
                all_data[y][hazard][state][m]
                for y in completed_years
                if state in all_data.get(y, {}).get(hazard, {})
            ]
            avg = round(sum(vals) / len(vals), 1) if vals else 0.0
            monthly_lta.append(avg)
        lta[hazard][state] = monthly_lta


# ── Write JSON (for inspection) ───────────────────────────────────────────────
output = {"lta": lta, "years": all_data}
json_path = os.path.join(OUTPUT_DIR, "storm_data.json")
with open(json_path, "w") as f:
    # Convert int year keys to strings for JSON compliance
    json.dump(
        {"lta": lta, "years": {str(k): v for k, v in all_data.items()}},
        f, indent=2
    )
print(f"\nJSON written → {json_path}")


# ── Write JS (paste into React app) ──────────────────────────────────────────
def js_array(arr):
    return "[" + ",".join(str(x) for x in arr) + "]"

def js_state_block(state_dict):
    lines = []
    for state, monthly in sorted(state_dict.items()):
        lines.append(f'    {state}:{js_array(monthly)}')
    return "{\n" + ",\n".join(lines) + "\n  }"

js_lines = [
    "// AUTO-GENERATED by fetch_storm_data.py — do not edit manually",
    "// Source: NOAA NCEI Storm Events Database",
    "// LTA computed from available years in this dataset",
    "",
    "export const REAL_LTA = {",
]
for hazard in ["tornado", "hail", "wind"]:
    js_lines.append(f"  {hazard}: {js_state_block(lta[hazard])},")
js_lines.append("};\n")

js_lines.append("export const REAL_YEAR_DATA = {")
for year, year_data in sorted(all_data.items()):
    js_lines.append(f"  {year}: {{")
    for hazard in ["tornado", "hail", "wind"]:
        js_lines.append(f"    {hazard}: {js_state_block(year_data[hazard])},")
    js_lines.append("  },")
js_lines.append("};\n")

js_path = os.path.join(OUTPUT_DIR, "storm_data.js")
with open(js_path, "w") as f:
    f.write("\n".join(js_lines))
print(f"JS written  → {js_path}")

print("\n✅ Done! Next steps:")
print("  1. Copy storm_data.js into your React project")
print("  2. Import REAL_LTA and REAL_YEAR_DATA at the top of storm-comparator.jsx")
print("  3. Replace LTA_BASE with REAL_LTA")
print("  4. Replace generateYearData() lookup with REAL_YEAR_DATA[year][state]")
print("  5. Remove the seededRng / fake data functions")
