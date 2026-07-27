"""Downloads the Amazon-Google Products entity-matching benchmark (Leipzig DB
group mirror of the classic Magellan/DeepMatcher dataset: 1363 Amazon products,
3226 Google products, 1300 gold-standard matches) and converts it into CSVs
compatible with our POST /datasets upload endpoint.
"""
import csv
import io
import random
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


def load_stratified_sample(
    positive_count: int = 150, negative_count: int = 150, seed: int = 42
) -> tuple[Path, Path, Path]:
    """Builds a stratified sample instead of a plain head-of-file truncation:
    `positive_count` Amazon records that have a known gold match (plus their
    matched Google counterparts), and `negative_count` additional Google records
    with no gold match at all (negative examples). Total ~positive_count Amazon +
    (positive_count + negative_count) Google records. Deterministic given `seed`,
    so re-running produces the same sample. Also writes a gold file scoped to just
    the sampled positive pairs — using the full 1300-pair gold file against this
    small sample would massively inflate false_negatives with pairs whose records
    were never even uploaded. Returns (amazon_csv_path, google_csv_path, gold_csv_path)."""
    if not (AMAZON_OUT.exists() and GOOGLE_OUT.exists() and GOLD_OUT.exists()):
        download_and_extract()

    with open(GOLD_OUT, encoding="utf-8", newline="") as f:
        gold_pairs = list(csv.DictReader(f))

    rng = random.Random(seed)
    rng.shuffle(gold_pairs)
    chosen_gold = gold_pairs[:positive_count]
    positive_amazon_ids = {row["idAmazon"] for row in chosen_gold}
    positive_google_ids = {row["idGoogleBase"] for row in chosen_gold}

    with open(AMAZON_OUT, encoding="utf-8", newline="") as f:
        amazon_reader = csv.DictReader(f)
        amazon_fieldnames = amazon_reader.fieldnames
        all_amazon_rows = list(amazon_reader)

    with open(GOOGLE_OUT, encoding="utf-8", newline="") as f:
        google_reader = csv.DictReader(f)
        google_fieldnames = google_reader.fieldnames
        all_google_rows = list(google_reader)

    amazon_by_id = {row["id"]: row for row in all_amazon_rows}
    google_by_id = {row["id"]: row for row in all_google_rows}

    sample_amazon_rows = [
        amazon_by_id[aid] for aid in positive_amazon_ids if aid in amazon_by_id
    ]
    sample_google_rows = [
        google_by_id[gid] for gid in positive_google_ids if gid in google_by_id
    ]

    non_match_google_rows = [
        row for row in all_google_rows if row["id"] not in positive_google_ids
    ]
    rng.shuffle(non_match_google_rows)
    negative_google_rows = non_match_google_rows[:negative_count]
    sample_google_rows.extend(negative_google_rows)

    amazon_sample_path = BENCHMARK_DIR / f"amazon_stratified_{positive_count}.csv"
    google_sample_path = BENCHMARK_DIR / f"google_stratified_{positive_count}_{negative_count}.csv"
    gold_sample_path = BENCHMARK_DIR / f"gold_stratified_{positive_count}.csv"

    _write_csv(amazon_sample_path, sample_amazon_rows, amazon_fieldnames)
    _write_csv(google_sample_path, sample_google_rows, google_fieldnames)
    _write_csv(gold_sample_path, chosen_gold, ["idAmazon", "idGoogleBase"])

    print(
        f"Stratified sample: {len(sample_amazon_rows)} Amazon "
        f"({len(positive_amazon_ids)} with a gold match), "
        f"{len(sample_google_rows)} Google "
        f"({len(positive_google_ids)} matched + {len(negative_google_rows)} unmatched negatives), "
        f"{len(chosen_gold)} gold pairs scoped to this sample"
    )

    return amazon_sample_path, google_sample_path, gold_sample_path


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    amazon_path, google_path = load_benchmark_pair(limit=limit)
    print(f"\nReady: {amazon_path}, {google_path}")
