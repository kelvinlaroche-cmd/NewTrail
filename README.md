# Miami-Dade Mortgage + Assessed Value Join

This repository contains a single script, `miami_dade_etl.py`, that builds the requested output:

- address
- parcel id
- assessed value
- mortgage recorded date
- book/page or instrument number

## Inputs

Provide either local CSV files or CSV URLs for:

1. Miami-Dade property roll / assessed-value data
2. Miami-Dade official records extract

The mortgage extract is filtered to `Doc Type = Mortgage` and a rolling lookback window (`--years`, default `2`).

## Run

```bash
./miami_dade_etl.py \
  --properties-csv path/to/properties.csv \
  --mortgages-csv path/to/official_records.csv \
  --output miami_dade_mortgage_assessed_join.csv
```

Or from URLs:

```bash
./miami_dade_etl.py \
  --properties-url "https://...properties.csv" \
  --mortgages-url "https://...mortgages.csv" \
  --output miami_dade_mortgage_assessed_join.csv
```

## Matching logic

1. Parcel/Folio ID exact match (preferred)
2. Normalized address match (street suffixes and unit numbers)

## Notes

- Column names are auto-detected using common aliases (`folio`, `parcel_id`, `recording_date`, etc.).
- If your source files use different headers, add aliases in `pick_col()`.
