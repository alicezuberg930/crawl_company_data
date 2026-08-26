# Masothue data crawler

Python scripts for collecting Vietnamese business categories, company URLs, and
company details from `masothue.com`. The crawlers persist checkpoints so an
interrupted run can continue without starting over.

## Requirements

- Python 3.10 or newer
- `requests`
- `beautifulsoup4`

```bash
python -m pip install requests beautifulsoup4
```

Run all commands from the repository root.

## Crawl workflow

### 1. Crawl business categories

```bash
python crawl_danh_muc.py
```

This creates:

- `crawl_data/danh_muc_nganh_nghe.json`: business categories

To discard existing output and start at page 1:

```bash
python crawl_danh_muc.py --restart
```

### 2. Crawl company URLs

```bash
python crawl_doanh_nghiep.py
```

The default input is `danh_muc_nganh_nghe.json`. Results are written to
`doanh_nghiep_urls.json`, and progress is stored in
`crawl_doanh_nghiep_state.json`.

To discard the checkpoint and crawl all categories again:

```bash
python crawl_doanh_nghiep.py --restart
```

### 3. Crawl company details

```bash
python crawl_masothue.py \
  --input doanh_nghiep_urls.json \
  --output doanh_nghiep_chi_tiet.json
```

Progress is stored in `crawl_masothue_state.json`. Failed URLs are written to
`failed_business_urls.json`. Subsequent runs resume from the checkpoint unless
`--restart` is supplied.

To crawl one company instead of a batch:

```bash
python crawl_masothue.py \
  --url "https://masothue.com/1102175850-cong-ty-tnhh-tmdv-ha-phi-nom-group" \
  --output company.json
```

Use `python <script>.py --help` to inspect optional output paths, delays,
checkpoints, and test-run limits supported by each crawler.

## Clean `main_business`

`clean_main_business.py` removes configured detail, inactivity, and exclusion
markers from string-valued `main_business` fields in a JSON array, then trims
trailing whitespace. It preserves all other fields and skips objects whose
`main_business` value is absent or is not a string. Matching is
case-insensitive.

The input must have this top-level structure:

```json
[
  {
    "tax_code": "1102175850",
    "main_business": "Bán buôn thực phẩm - Chi tiết: Bán buôn cà phê"
  }
]
```

Replace the input file safely in place:

```bash
python clean_main_business.py doanh_nghiep_chi_tiet.json
```

The in-place operation writes a temporary file in the same directory and then
atomically replaces the source file.

Keep the source file unchanged and write cleaned data to another file:

```bash
python clean_main_business.py \
  doanh_nghiep_chi_tiet.json \
  --output doanh_nghiep_chi_tiet_clean.json
```

The command reports how many objects changed and the destination path:

```text
Cleaned main_business in 42 objects in doanh_nghiep_chi_tiet_clean.json.
```

The script fails if the top-level JSON value is not an array or any array item
is not an object.

## Clean `legal_representative`

`clean_legal_representative.py` removes text from `legal_representative`
starting at `Ngoài ra` when that phrase starts a sentence segment, then trims
trailing whitespace. It preserves all other fields and skips objects whose
`legal_representative` value is absent or is not a string. Matching is
case-insensitive.

Replace the input file safely in place:

```bash
python clean_legal_representative.py doanh_nghiep_chi_tiet.json
```

Keep the source file unchanged and write cleaned data to another file:

```bash
python clean_legal_representative.py \
  doanh_nghiep_chi_tiet.json \
  --output doanh_nghiep_chi_tiet_clean.json
```

The command reports how many objects changed and the destination path:

```text
Cleaned legal_representative in 42 objects in doanh_nghiep_chi_tiet_clean.json.
```

The script fails if the top-level JSON value is not an array or any array item
is not an object.

## Other data utilities

Replace each object's `business_code` with its one-based array position:

```bash
python update_business_codes.py doanh_nghiep_chi_tiet.json
```

Use `--output <path>` to preserve the source file.
