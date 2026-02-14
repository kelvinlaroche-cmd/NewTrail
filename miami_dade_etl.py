#!/usr/bin/env python3
"""Build a Miami-Dade mortgage-to-assessment extract.

Inputs can be local CSV files or remote CSV URLs.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

SUFFIX_MAP = {
    "STREET": "ST",
    "ST": "ST",
    "ROAD": "RD",
    "RD": "RD",
    "AVENUE": "AVE",
    "AVE": "AVE",
    "BOULEVARD": "BLVD",
    "BLVD": "BLVD",
    "DRIVE": "DR",
    "DR": "DR",
    "LANE": "LN",
    "LN": "LN",
    "COURT": "CT",
    "CT": "CT",
    "PLACE": "PL",
    "PL": "PL",
    "TERRACE": "TER",
    "TER": "TER",
    "CIRCLE": "CIR",
    "CIR": "CIR",
}

UNIT_PAT = re.compile(r"\b(?:APT|UNIT|STE|SUITE|#)\s*([A-Z0-9-]+)\b")
SPACE_PAT = re.compile(r"\s+")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--properties-csv", help="Local property roll CSV path")
    p.add_argument("--mortgages-csv", help="Local mortgage records CSV path")
    p.add_argument("--properties-url", help="CSV URL for property roll")
    p.add_argument("--mortgages-url", help="CSV URL for mortgage instruments")
    p.add_argument("--output", default="miami_dade_mortgage_assessed_join.csv")
    p.add_argument("--years", type=int, default=2, help="Rolling lookback window")
    return p.parse_args()


def fetch_csv_text(path: str | None, url: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8-sig")
    if url:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=90) as response:
            return response.read().decode("utf-8-sig", errors="replace")
    raise ValueError("Provide either a local path or URL for each input CSV")


def pick_col(row: dict[str, str], candidates: list[str]) -> str:
    lowered = {k.lower().strip(): k for k in row}
    for cand in candidates:
        key = lowered.get(cand.lower())
        if key:
            return row.get(key, "").strip()
    return ""


def normalize_address(addr: str) -> str:
    a = addr.upper().strip().replace("#", " UNIT ")
    unit_match = UNIT_PAT.search(a)
    unit = unit_match.group(1) if unit_match else ""
    a = UNIT_PAT.sub("", a)
    a = re.sub(r"[^A-Z0-9\s]", " ", a)
    parts = [p for p in SPACE_PAT.sub(" ", a).strip().split(" ") if p]
    if not parts:
        return ""
    parts = [SUFFIX_MAP.get(p, p) for p in parts]
    return " ".join(parts + ([f"UNIT {unit}"] if unit else []))


def parse_date(value: str) -> dt.date | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%m-%d-%Y"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def load_properties(text: str) -> tuple[dict[str, dict], dict[str, dict]]:
    by_parcel: dict[str, dict] = {}
    by_addr: dict[str, dict] = {}
    for row in csv.DictReader(io.StringIO(text)):
        parcel_id = pick_col(row, ["parcel_id", "folio", "folio_number", "parcel", "pin"])
        address = pick_col(row, ["address", "site_address", "property_address", "situs_address"])
        assessed = pick_col(row, ["assessed_value", "assessed", "total_assessed_value", "market_value"]) 
        rec = {
            "address": address,
            "parcel_id": parcel_id,
            "assessed_value": assessed,
            "norm_address": normalize_address(address),
        }
        if parcel_id:
            by_parcel[parcel_id] = rec
        if rec["norm_address"]:
            by_addr[rec["norm_address"]] = rec
    return by_parcel, by_addr


def load_mortgages(text: str, years: int) -> list[dict]:
    cutoff = dt.date.today() - dt.timedelta(days=365 * years)
    out: list[dict] = []
    for row in csv.DictReader(io.StringIO(text)):
        doc_type = pick_col(row, ["doc_type", "document_type", "doctype", "doc type"])
        if doc_type.upper() != "MORTGAGE":
            continue
        rec_date_raw = pick_col(row, ["recording_date", "recorded_date", "record_date", "recording date"])
        rec_date = parse_date(rec_date_raw)
        if rec_date is None or rec_date < cutoff:
            continue
        out.append(
            {
                "address": pick_col(row, ["address", "property_address", "legal_address", "situs_address"]),
                "parcel_id": pick_col(row, ["parcel_id", "folio", "folio_number", "pin", "parcel"]),
                "recording_date": rec_date.isoformat(),
                "instrument_number": pick_col(row, ["instrument_number", "instrument", "cfn", "doc_number"]),
                "book_page": pick_col(row, ["book_page", "book/page", "book_page_ref"]),
            }
        )
    return out


def join_records(mortgages: list[dict], by_parcel: dict[str, dict], by_addr: dict[str, dict]) -> list[dict]:
    joined = []
    for m in mortgages:
        prop = None
        if m["parcel_id"]:
            prop = by_parcel.get(m["parcel_id"])
        if prop is None:
            prop = by_addr.get(normalize_address(m["address"]))
        joined.append(
            {
                "address": m["address"] or (prop["address"] if prop else ""),
                "parcel_id": m["parcel_id"] or (prop["parcel_id"] if prop else ""),
                "assessed_value": prop["assessed_value"] if prop else "",
                "mortgage_recorded_date": m["recording_date"],
                "book_page_or_instrument_number": m["book_page"] or m["instrument_number"],
            }
        )
    return joined


def main() -> int:
    args = parse_args()
    try:
        prop_text = fetch_csv_text(args.properties_csv, args.properties_url)
        mtg_text = fetch_csv_text(args.mortgages_csv, args.mortgages_url)
    except Exception as exc:
        print(f"Input load failed: {exc}", file=sys.stderr)
        return 1

    by_parcel, by_addr = load_properties(prop_text)
    mortgages = load_mortgages(mtg_text, args.years)
    result = join_records(mortgages, by_parcel, by_addr)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "address",
        "parcel_id",
        "assessed_value",
        "mortgage_recorded_date",
        "book_page_or_instrument_number",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result)

    print(f"Wrote {len(result)} rows to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
