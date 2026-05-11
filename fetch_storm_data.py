#!/usr/bin/env python3
"""
fetch_storm_data.py
-------------------
Downloads NOAA Storm Events CSVs for 1991–present, plus SPC daily reports
for the current year (which NOAA hasn't published yet), and writes:

  storm_data.js   — embedded directly into app.jsx (STORM_DATA constant)
  storm_data.json — raw numbers for inspection

Run from your project folder:
    cd /Users/stevejaye/Documents/vibe_apps/SevereStorm_Comparison
    pip install requests pandas
    python fetch_storm_data.py
"""

import os
import io
import json
import datetime
import requests
import pandas as pd

# ── Configuration ──────────────────────────────────────────────────────────────

OUTPUT_DIR  = os.path.dirname(os.path.abspath(__file__))
CURRENT_YEAR = datetime.date.today().year
YEARS       = list(range(1991, CURRENT_YEAR + 1))
CACHE_DIR   = os.path.join(OUTPUT_DIR, "_cache")
SPC_CACHE_DIR = os.path.join(CACHE_DIR, "spc")
BASE_URL    = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
SPC_URL     = "https://www.spc.noaa.gov/climo/reports/{date}_rpts.csv"

EVENT_MAP = {
    "Tornado":           "tornado",
    "Hail":              "hail",
    "Thunderstorm Wind": "wind",
}

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

APP_STATES = [
    "AL","AR","AZ","CA","CO","CT","DE","FL","GA","IA","ID","IL","IN","KS","KY",
    "LA","MA","MD","ME","MI","MN","MO","MS","MT","NC","ND","NE","NH","NJ","NM",
    "NV","NY","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VA","VT","WA",
    "WI","WV","WY"
]

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
    "LAKE ST. CLAIR":"MI","LAKE MICHIGAN":"IL",
}

os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(SPC_CACHE_DIR, exist_ok=True)


# ── NOAA helpers ───────────────────────────────────────────────────────────────

def find_detail_filename(year):
    print(f"  Checking index for year {year}...")
    resp = requests.get(BASE_URL, timeout=30)
    resp.raise_for_status()
    for line in resp.text.splitlines():
        if f"_details-ftp_v1.0_d{year}_" in line and ".csv.gz" in line:
            start = line.find('href="') + 6
            end   = line.find('"', start)
            return line[start:end]
    return None


def download_and_cache_noaa(year):
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

    import gzip
    with gzip.open(io.BytesIO(resp.content), "rt", encoding="latin-1") as gz:
        content = gz.read()
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  [{year}] Saved to cache.")
    return cache_path


def load_noaa_year(year):
    path = download_and_cache_noaa(year)
    if path is None:
        return None

    df = pd.read_csv(path, low_memory=False, encoding="utf-8")
    df.columns = [c.strip().upper() for c in df.columns]

    needed = ["STATE_FIPS", "STATE", "EVENT_TYPE", "MONTH_NAME", "BEGIN_DATE_TIME"]
    col_map = {}
    for col in df.columns:
        for n in needed:
            if col == n or col.replace(" ", "_") == n:
                col_map[n] = col
    df = df.rename(columns={v: k for k, v in col_map.items()})

    df = df[df["EVENT_TYPE"].isin(EVENT_MAP.keys())].copy()
    df["hazard"] = df["EVENT_TYPE"].map(EVENT_MAP)

    month_nums = {
        "January":1,"February":2,"March":3,"April":4,"May":5,"June":6,
        "July":7,"August":8,"September":9,"October":10,"November":11,"December":12
    }
    df["month"] = df["MONTH_NAME"].map(month_nums)
    df = df.dropna(subset=["month"])
    df["month"] = df["month"].astype(int)

    df["state_abbr"] = df["STATE"].str.strip().str.upper().map(STATE_NAME_TO_ABBR)
    df = df[df["state_abbr"].isin(APP_STATES)]
    return df


def aggregate_noaa(df):
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
                monthly.append(round(count / area_10k, 1))
            state_data[state] = monthly
        year_data[hazard] = state_data
    return year_data


# ── SPC daily reports fetcher (current year only) ─────────────────────────────

def fetch_spc_year(year):
    """
    Downloads SPC daily storm reports for every day Jan 1 → yesterday.
    Data is preliminary but updates within ~24 hours of each event.
    Cached per-day in _cache/spc/; only re-downloads missing days.
    """
    start = datetime.date(year, 1, 1)
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    end = min(yesterday, datetime.date(year, 12, 31))

    # raw event counts per hazard/state/month (before area normalisation)
    counts = {
        h: {s: [0] * 12 for s in APP_STATES}
        for h in ["tornado", "hail", "wind"]
    }

    total_days = 0
    total_events = 0
    date = start
    while date <= end:
        yy = str(date.year)[2:]
        datestr = f"{yy}{date.month:02d}{date.day:02d}"
        cache_path = os.path.join(SPC_CACHE_DIR, f"{datestr}_rpts.csv")

        if not os.path.exists(cache_path):
            url = SPC_URL.format(date=datestr)
            try:
                resp = requests.get(url, timeout=15)
                if resp.status_code == 200:
                    with open(cache_path, "w", encoding="latin-1") as f:
                        f.write(resp.text)
                else:
                    date += datetime.timedelta(days=1)
                    continue
            except Exception:
                date += datetime.timedelta(days=1)
                continue

        # Parse: file has 3 sections separated by header rows
        # Header patterns: "Time,F_Scale,..." / "Time,Speed,..." / "Time,Size,..."
        try:
            with open(cache_path, "r", encoding="latin-1") as f:
                lines = f.read().splitlines()

            section = None
            for line in lines:
                if line.startswith("Time,F_Scale"):
                    section = "tornado"
                elif line.startswith("Time,Speed"):
                    section = "wind"
                elif line.startswith("Time,Size"):
                    section = "hail"
                elif section and line.strip():
                    parts = line.split(",")
                    if len(parts) >= 5:
                        state = parts[4].strip().upper()
                        if state in APP_STATES:
                            counts[section][state][date.month - 1] += 1
                            total_events += 1
        except Exception:
            pass

        total_days += 1
        date += datetime.timedelta(days=1)

    print(f"  SPC: {total_days} days downloaded, {total_events} events counted.")

    # Normalise by state area
    result = {}
    for hazard in ["tornado", "hail", "wind"]:
        result[hazard] = {}
        for state in APP_STATES:
            area_10k = STATE_AREA_SQMI.get(state, 50000) / 10000
            result[hazard][state] = [
                round(c / area_10k, 1) for c in counts[hazard][state]
            ]
    return result


# ── Main processing ────────────────────────────────────────────────────────────

print("=" * 60)
print("NOAA Storm Events Data Fetcher")
print("=" * 60)

all_data = {}

for year in YEARS:
    print(f"\nProcessing {year}...")

    if year == CURRENT_YEAR:
        # Use SPC preliminary daily reports — more current than NOAA
        print(f"  Using SPC preliminary daily reports for {year}...")
        year_data = fetch_spc_year(year)
        all_data[year] = year_data
        print(f"  Done.")
    else:
        df = load_noaa_year(year)
        if df is None:
            print(f"  Skipping {year} (no data available yet).")
            continue
        all_data[year] = aggregate_noaa(df)
        print(f"  Done — {len(df)} events processed.")


# ── Compute LTA from verified completed years (not current year) ──────────────
print("\nComputing LTA from verified years...")
completed_years = [y for y in YEARS if y in all_data and y < CURRENT_YEAR]

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


# ── Write JSON ────────────────────────────────────────────────────────────────
json_path = os.path.join(OUTPUT_DIR, "storm_data.json")
with open(json_path, "w") as f:
    json.dump(
        {"lta": lta, "years": {str(k): v for k, v in all_data.items()}},
        f, indent=2
    )
print(f"\nJSON written → {json_path}")


# ── Write JS ──────────────────────────────────────────────────────────────────
def js_array(arr):
    return "[" + ",".join(str(x) for x in arr) + "]"

def js_state_block(state_dict):
    lines = []
    for state, monthly in sorted(state_dict.items()):
        lines.append(f'    {state}:{js_array(monthly)}')
    return "{\n" + ",\n".join(lines) + "\n  }"

js_lines = [
    "// AUTO-GENERATED by fetch_storm_data.py — do not edit manually",
    f"// NOAA NCEI (1991–{CURRENT_YEAR - 1}) + SPC preliminary ({CURRENT_YEAR})",
    "// LTA computed from verified years only",
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

print(f"\n✅ Done! {CURRENT_YEAR} data sourced from SPC preliminary reports.")
print("   Re-run this script anytime to refresh with the latest SPC data.")
