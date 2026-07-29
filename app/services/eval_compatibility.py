from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Dataset, Record
from app.services.compatibility_check import run_compatibility_check
from app.services.file_parsing import parse_upload
from app.services.schema_mapping import infer_schema_mapping

SAMPLE_DATA_DIR = Path(__file__).parent.parent.parent / "scripts" / "sample_data"
BENCHMARK_DIR = SAMPLE_DATA_DIR / "benchmarks" / "amazon_google"

# (label, file_a, file_b, expected_verdict)
COMPATIBILITY_TEST_MATRIX = [
    ("products_vs_products_v2", SAMPLE_DATA_DIR / "products.csv", SAMPLE_DATA_DIR / "products_v2.csv", "compatible"),
    ("products_vs_products_v3", SAMPLE_DATA_DIR / "products.csv", SAMPLE_DATA_DIR / "products_v3.csv", "compatible"),
    ("products_vs_restaurants", SAMPLE_DATA_DIR / "products.csv", SAMPLE_DATA_DIR / "restaurants.csv", "incompatible"),
    (
        "amazon_vs_google_stratified",
        BENCHMARK_DIR / "amazon_stratified_150.csv",
        BENCHMARK_DIR / "google_stratified_150_150.csv",
        "compatible",
    ),
]


def _ingest_dataset(db: Session, path: Path) -> Dataset:
    """Mirrors POST /datasets' ingestion logic directly against the DB, so this
    eval doesn't depend on the HTTP server being up. Always creates a fresh
    Dataset/Record set (no dedup) — each eval run gets its own isolated data."""
    content = path.read_bytes()
    rows = parse_upload(path.name, content)

    headers = list(rows[0].keys())
    schema_mapping = infer_schema_mapping(headers, rows)

    dataset = Dataset(
        name=path.name,
        source_filename=path.name,
        schema_mapping=schema_mapping,
        uploaded_at=datetime.now(timezone.utc),
    )
    db.add(dataset)
    db.flush()

    for row in rows:
        canonical_json = {
            canonical_field: row.get(source_column)
            for canonical_field, source_column in schema_mapping.items()
        }
        db.add(Record(dataset_id=dataset.id, raw_json=row, canonical_json=canonical_json))

    db.flush()
    return dataset


def run_compatibility_check_eval(db: Session) -> dict:
    """Runs the compatibility check against a small, deliberately-labeled test
    matrix (Section 8.4): known-compatible pairs and a known-incompatible pair,
    reporting a simple pass/fail table rather than precision/recall — this is a
    small labeled matrix, not a statistical sample."""
    results = []

    for label, path_a, path_b, expected_verdict in COMPATIBILITY_TEST_MATRIX:
        dataset_a = _ingest_dataset(db, path_a)
        dataset_b = _ingest_dataset(db, path_b)

        compatibility_check = run_compatibility_check(db, dataset_a, dataset_b)
        actual_verdict = compatibility_check["verdict"]
        passed = actual_verdict == expected_verdict

        results.append(
            {
                "label": label,
                "file_a": path_a.name,
                "file_b": path_b.name,
                "expected_verdict": expected_verdict,
                "actual_verdict": actual_verdict,
                "passed": passed,
                "reasoning": compatibility_check["reasoning"],
                "signals": compatibility_check["signals"],
            }
        )

    db.commit()

    pass_count = sum(1 for r in results if r["passed"])
    return {
        "total_cases": len(results),
        "passed": pass_count,
        "failed": len(results) - pass_count,
        "cases": results,
    }
