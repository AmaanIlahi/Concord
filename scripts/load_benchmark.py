"""Downloads the Amazon-Google Products entity-matching benchmark (Leipzig DB
group mirror of the classic Magellan/DeepMatcher dataset: 1363 Amazon products,
3226 Google products, 1300 gold-standard matches) and converts it into CSVs
compatible with our POST /datasets upload endpoint.
"""
import csv
import io
import sys
import zipfile
from pathlib import Path

import requests

DATASET_URL = "https://dbs.uni-leipzig.de/files/datasets/Amazon-GoogleProducts.zip"
SOURCE_ENCODING = "cp1252"

BENCHMARK_DIR = Path(__file__).parent / "sample_data" / "benchmarks" / "amazon_google"
AMAZON_OUT = BENCHMARK_DIR / "amazon.csv"
GOOGLE_OUT = BENCHMARK_DIR / "google.csv"
GOLD_OUT = BENCHMARK_DIR / "gold_matches.csv"


def download_and_extract() -> None:
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {DATASET_URL} ...")
    response = requests.get(DATASET_URL, timeout=60)
    response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        amazon_rows = _read_csv_member(zf, "Amazon.csv")
        google_rows = _read_csv_member(zf, "GoogleProducts.csv")
        gold_rows = _read_csv_member(zf, "Amzon_GoogleProducts_perfectMapping.csv")

    _write_csv(AMAZON_OUT, amazon_rows, ["id", "title", "description", "manufacturer", "price"])
    _write_csv(GOOGLE_OUT, google_rows, ["id", "name", "description", "manufacturer", "price"])
    _write_csv(GOLD_OUT, gold_rows, ["idAmazon", "idGoogleBase"])

    print(f"Wrote {len(amazon_rows)} Amazon rows -> {AMAZON_OUT}")
    print(f"Wrote {len(google_rows)} Google rows -> {GOOGLE_OUT}")
    print(f"Wrote {len(gold_rows)} gold matches -> {GOLD_OUT}")


def _read_csv_member(zf: zipfile.ZipFile, member_name: str) -> list[dict]:
    raw = zf.read(member_name).decode(SOURCE_ENCODING)
    return list(csv.DictReader(io.StringIO(raw)))


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_benchmark_pair(limit: int | None = None) -> tuple[Path, Path]:
    """Ensures the benchmark CSVs exist (downloading if needed), and returns
    (amazon_csv_path, google_csv_path) truncated to `limit` rows each if given.
    Truncated copies are written alongside the full files, suffixed `_sample`."""
    if not (AMAZON_OUT.exists() and GOOGLE_OUT.exists() and GOLD_OUT.exists()):
        download_and_extract()

    if limit is None:
        return AMAZON_OUT, GOOGLE_OUT

    amazon_sample = BENCHMARK_DIR / f"amazon_sample_{limit}.csv"
    google_sample = BENCHMARK_DIR / f"google_sample_{limit}.csv"

    with open(AMAZON_OUT, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = [row for _, row in zip(range(limit), reader)]
        _write_csv(amazon_sample, rows, reader.fieldnames)

    with open(GOOGLE_OUT, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = [row for _, row in zip(range(limit), reader)]
        _write_csv(google_sample, rows, reader.fieldnames)

    return amazon_sample, google_sample


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    amazon_path, google_path = load_benchmark_pair(limit=limit)
    print(f"\nReady: {amazon_path}, {google_path}")
