# Day 2: Multi-File Data Processing Pipeline

Validates, cleans and consolidates daily branch transaction files from Soko Fresh Supermarkets into one trusted dataset, and keeps a separate, explainable record of every row it rejects.

## Approach

`pipeline.py` runs eight steps, using only the Python standard library (no pandas):

1. **Discover:** `discover_files` finds every `transactions_*.csv` in the input folder with `Path.glob`, sorted by date.
2. **Read:** `read_transactions` reads each file with `csv.DictReader` and tags every row with its source file and line number.
3. **Validate columns:** `validate_columns` uses set difference to find missing required columns. Known renames are mapped by `apply_aliases`; a file still missing columns is rejected and reported.
4. **Find problems:** `find_problems` lists every reason a row is invalid: blank required fields, non-numeric or non-positive quantity/price, and transaction IDs already accepted earlier in the run.
5. **Clean:** `clean_row` strips whitespace, converts numbers to `int`, adds `line_total`, and keeps only the output columns.
6. **Combine:** accepted rows are written to `output/consolidated_transactions.csv`.
7. **Reject:** every rejected row is written to `output/rejected_transactions.csv` with its source file, row number and all reasons.
8. **Summarise:** `build_summary` prints a processing summary and saves it to `output/summary.txt`. Before writing, the pipeline checks that rows read (counted while reading) equals accepted + rejected, and stops if they differ.

## How to run

Requires Python 3.10 or newer. No third-party packages are needed.

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python pipeline.py
```

On Mac or Linux, activate with `source venv/bin/activate`. By default the pipeline reads from `data/` and writes to `output/`. Both can be changed:

```
python pipeline.py --input data/ --output output/
```

Run `python pipeline.py --help` to see all options. To add a new day, drop its `transactions_YYYY-MM-DD.csv` into the input folder; no code changes are needed.

## Outputs

| File | Contents |
| --- | --- |
| `output/consolidated_transactions.csv` | Every accepted transaction, once, with `line_total` and `source_file` (34 rows) |
| `output/rejected_transactions.csv` | Every rejected row with `source_file`, `row_number`, `transaction_id`, all `reasons`, and its original values (9 rows) |
| `output/summary.txt` | The processing summary: files, rows read/accepted/rejected by reason, and total revenue (KES 22,775) |

## Data findings

Before writing the pipeline, I inspected all three input files by hand. These findings became the test plan.

| File | Rows | Problems found |
| --- | --- | --- |
| `transactions_2026-10-01.csv` | 15 | None |
| `transactions_2026-10-02.csv` | 16 | Blank `customer_id` (TXN-1018), blank `unit_price` (TXN-1019), blank `quantity` (TXN-1021), blank `branch` (TXN-1025), non-numeric quantity `"two"` (TXN-1028), TXN-1012 re-sent from day 1, TXN-1023 repeated within the file |
| `transactions_2026-10-03.csv` | 12 | Header renamed `quantity` to `qty` and added a `cashier` column (POS upgrade), negative quantity `-4` (TXN-1035), TXN-1029 re-sent from day 2 |

Expected result: 43 rows read, 34 accepted, 9 rejected (4 missing values, 2 invalid numbers, 3 duplicate IDs).

## Assumptions

- **`payment_ref` is optional.** Every row with a blank `payment_ref` is a Cash sale, and cash has no reference number. It is also not in `REQUIRED_COLUMNS`. Treating it as missing would throw away every cash sale.
- **Extra columns are ignored.** Day 3's new `cashier` column is not required and is not in the expected output, so it is dropped rather than causing the file to fail.
- **Quantities and prices must be positive whole numbers.** Prices are in whole Kenyan shillings and quantities are counted items, so decimals are rejected as invalid. A negative quantity (TXN-1035) is rejected rather than treated as a refund; refunds belong in a separate process, and keeping it would subtract revenue.
- **New files need no code changes.** `discover_files` uses `Path.glob("transactions_*.csv")` and sorts by name; ISO dates (`YYYY-MM-DD`) sort alphabetically in date order. Tested by temporarily adding a copy named `transactions_2026-10-04.csv`, which was picked up automatically, while a `notes.txt` was ignored.
- **Renamed column: mapped, not rejected.** Day 3's POS upgrade renamed `quantity` to `qty`. Rejecting the whole file would remove a full day of sales from every branch, even though the data itself is fine, so the pipeline maps the alias instead. To keep this safe: `COLUMN_ALIASES` is an explicit allowlist containing only `qty → quantity`, which I confirmed by inspecting the file (the values are quantities); any other unexpected header still fails validation; columns are validated again after mapping; and the summary reports the file as having a column issue so finance knows it happened.
- **Duplicates: the first valid copy is kept.** Files are processed in date order, and a transaction ID is only recorded as "seen" once its row is accepted. Later copies (TXN-1012 and TXN-1029, re-sent by retries, and the second TXN-1023 within day 2) are rejected as duplicates and listed in the rejected report. Recording only accepted IDs means that if the first copy of a sale were invalid, a later complete copy would still be accepted instead of being lost.

## Error handling

Problems with the run itself print one clear `Error: ...` message and exit with code 1, instead of a raw traceback.

| Situation | What happens | Tested |
| --- | --- | --- |
| Input folder does not exist | `Error: Input folder not found: ...` | `python pipeline.py --input nowhere`, then `echo %ERRORLEVEL%` printed `1` |
| No `transactions_*.csv` files in the folder | `Error: No transactions_*.csv files found in ...` (stops instead of writing empty outputs) | `python pipeline.py --input empty_test` (an empty folder) |
| Empty or unusable file (e.g. no header) | Reported as a column issue in the summary and skipped; the other files are still processed | Created an empty `transactions_2026-10-04.csv`: reported as "file rejected", no crash |
| Output file open in another program (e.g. Excel) | `Error: cannot write ... Is it open in Excel? Close it and run again.` | Ran with the consolidated CSV open in Excel |
| Rows read does not equal accepted + rejected | `Error: Reconciliation failed: ...` (stops before writing incomplete outputs) | Safeguard; not triggered by the provided data |