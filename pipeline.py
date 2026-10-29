"""
Day 2 - Multi-File Data Processing Pipeline
Squad Python Specialization - Data Engineering

Discovers daily branch transaction files, validates and cleans every row, and
writes consolidated, rejected and summary outputs that reconcile with rows read.

Usage:  python pipeline.py --input data/ --output output/
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path


REQUIRED_COLUMNS: set[str] = {
    "transaction_id", "date", "branch", "customer_id",
    "product", "quantity", "unit_price", "payment_method",
}

# Known, manually verified column renames. Day 3's POS upgrade renamed quantity to qty.
# Any other unexpected header still fails validation (see README).
COLUMN_ALIASES: dict[str, str] = {"qty": "quantity"}
NUMERIC_COLUMNS: tuple[str, ...] = ("quantity", "unit_price")
OUTPUT_COLUMNS: list[str] = [
    "transaction_id", "date", "branch", "customer_id", "product",
    "quantity", "unit_price", "line_total", "payment_method", "payment_ref", "source_file",
]
REJECTED_COLUMNS: list[str] = [
    "source_file", "row_number", "transaction_id", "reasons",
    "date", "branch", "customer_id", "product", "quantity", "unit_price",
    "payment_method", "payment_ref",
]


def discover_files(folder: Path, pattern: str = "transactions_*.csv") -> list[Path]:
    """Return the matching CSV files in a stable (date) order using pathlib."""
    return sorted(folder.glob(pattern))


def read_transactions(path: Path) -> tuple[list[str], list[dict]]:
    """Read one file and return (header, rows). Every row should remember its source file."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        rows = []
        for line_number, row in enumerate(reader, start=2):
            row["_source_file"] = path.name
            row["_row_number"] = line_number
            rows.append(row)
    return header, rows


def validate_columns(header: list[str], required: set[str] = REQUIRED_COLUMNS) -> set[str]:
    """Return the set of required columns missing from the header (empty set means valid)."""
    return required - set(header)


def apply_aliases(header: list[str], rows: list[dict],
                  aliases: dict[str, str] = COLUMN_ALIASES) -> tuple[list[str], list[dict]]:
    """Rename known alias columns (e.g. qty -> quantity) in the header and every row."""
    new_header = [aliases.get(col, col) for col in header]
    new_rows = [{aliases.get(key, key): value for key, value in row.items()} for row in rows]
    return new_header, new_rows


def find_problems(row: dict, seen_ids: set[str]) -> list[str]:
    """Return a list of human-readable reasons this row is invalid (empty list means valid).

    Must cover: blank required values, non-numeric or non-positive quantity/price,
    and transaction IDs already seen in this run.
    """
    problems = []

    # 1. Blank required fields
    for col in sorted(REQUIRED_COLUMNS):
        if not (row.get(col) or "").strip():
            problems.append(f"missing {col}")

    # 2. Quantity and price must be positive whole numbers
    for col in NUMERIC_COLUMNS:
        value = (row.get(col) or "").strip()
        if not value:
            continue  # already reported as missing above
        try:
            number = int(value)
        except ValueError:
            problems.append(f"invalid {col} '{value}': not a whole number")
            continue
        if number <= 0:
            problems.append(f"invalid {col} '{value}': must be positive")

    # 3. Duplicate transaction IDs (seen earlier in this run, in any file)
    transaction_id = (row.get("transaction_id") or "").strip()
    if transaction_id and transaction_id in seen_ids:
        problems.append(f"duplicate transaction_id {transaction_id}")

    return problems


def clean_row(row: dict) -> dict:
    """Return a normalised copy of a valid row (types converted, whitespace stripped)."""
    data_columns = set(OUTPUT_COLUMNS) - {"line_total", "source_file"}
    cleaned = {key: (value or "").strip() for key, value in row.items() if key in data_columns}
    for col in NUMERIC_COLUMNS:
        cleaned[col] = int(cleaned[col])
    cleaned["line_total"] = cleaned["quantity"] * cleaned["unit_price"]
    cleaned["source_file"] = row["_source_file"]
    return cleaned


def make_rejected(row: dict, reasons: list[str]) -> dict:
    """Build one rejected record: where it came from, why, and its original values."""
    return {
        "source_file": row["_source_file"],
        "row_number": row["_row_number"],
        "transaction_id": (row.get("transaction_id") or "").strip(),
        "reasons": "; ".join(reasons),
        **{k: v for k, v in row.items() if not k.startswith("_")},
    }


def write_csv(rows: list[dict], path: Path, fieldnames: list[str]) -> None:
    """Write rows to CSV, creating parent folders as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_summary(stats: dict) -> str:
    """Format the processing summary shown in the expected-output resource."""
    issues = stats["column_issues"]
    issue_detail = f"  ({'; '.join(issues)})" if issues else ""
    lines = [
        "=== Processing summary ===",
        f"Files discovered:        {stats['files_discovered']}",
        f"Files processed:         {stats['files_processed']}",
        f"Files with column issues:{len(issues)}{issue_detail}",
        f"Rows read:               {stats['rows_read']}",
        f"Rows accepted:           {stats['rows_accepted']}",
        f"Rows rejected:           {stats['rows_rejected']}",
        f"  - missing values:      {stats['missing_values']}",
        f"  - invalid numbers:     {stats['invalid_numbers']}",
        f"  - duplicate IDs:       {stats['duplicate_ids']}",
        f"Total revenue (KES):     {stats['total_revenue']:,}",
        f"Run finished at:         {stats['finished_at']}",
    ]
    return "\n".join(lines)


def run_pipeline(input_dir: Path, output_dir: Path) -> dict:
    """Run every step and return the statistics used by build_summary()."""
    files = discover_files(input_dir)
    if not files:
        raise RuntimeError(f"No transactions_*.csv files found in {input_dir}")

    seen_ids = set()
    accepted = []
    rejected = []
    rows_read = 0
    files_processed = 0
    column_issues = []

    for path in files:
        header, rows = read_transactions(path)
        rows_read += len(rows)

        missing = validate_columns(header)
        if missing:
            header, rows = apply_aliases(header, rows)
            still_missing = validate_columns(header)
            issue = f"{path.name}: missing {', '.join(sorted(missing))}"
            if still_missing:
                column_issues.append(issue + " (file rejected)")
                reason = f"file missing required columns: {', '.join(sorted(still_missing))}"
                rejected.extend(make_rejected(row, [reason]) for row in rows)
                continue
            column_issues.append(issue + " (mapped from alias)")
        files_processed += 1

        for row in rows:
            problems = find_problems(row, seen_ids)
            if problems:
                rejected.append(make_rejected(row, problems))
            else:
                seen_ids.add(row["transaction_id"].strip())
                accepted.append(clean_row(row))

    if rows_read != len(accepted) + len(rejected):
        raise RuntimeError(
            f"Reconciliation failed: read {rows_read} rows but accounted for "
            f"{len(accepted) + len(rejected)}"
        )

    write_csv(accepted, output_dir / "consolidated_transactions.csv", OUTPUT_COLUMNS)
    write_csv(rejected, output_dir / "rejected_transactions.csv", REJECTED_COLUMNS)

    def count_category(prefix: str) -> int:
        return sum(
            any(reason.startswith(prefix) for reason in r["reasons"].split("; "))
            for r in rejected
        )

    return {
        "files_discovered": len(files),
        "files_processed": files_processed,
        "column_issues": column_issues,
        "rows_read": rows_read,
        "rows_accepted": len(accepted),
        "rows_rejected": len(rejected),
        "missing_values": count_category("missing"),
        "invalid_numbers": count_category("invalid"),
        "duplicate_ids": count_category("duplicate"),
        "total_revenue": sum(row["line_total"] for row in accepted),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate, clean and consolidate daily branch transaction files."
    )
    parser.add_argument("--input", type=Path, default=Path("data"),
                        help="folder containing transactions_*.csv files (default: data)")
    parser.add_argument("--output", type=Path, default=Path("output"),
                        help="folder to write results to (default: output)")
    args = parser.parse_args()

    try:
        if not args.input.is_dir():
            raise RuntimeError(f"Input folder not found: {args.input}")
        stats = run_pipeline(args.input, args.output)
        summary = build_summary(stats)
        print(summary)
        (args.output / "summary.txt").write_text(summary + "\n", encoding="utf-8")
    except PermissionError as error:
        print(f"Error: cannot write {error.filename}. Is it open in Excel? Close it and run again.",
              file=sys.stderr)
        sys.exit(1)
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)