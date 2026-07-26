from app.db import SessionLocal
from app.models import Record
from app.services.bulk_embedding import embed_dataset_records
from _compat_check_utils import upload


def main():
    dataset_a_id = upload("products.csv")
    dataset_b_id = upload("products_v2.csv")

    db = SessionLocal()
    try:
        for label, dataset_id in [("products.csv", dataset_a_id), ("products_v2.csv", dataset_b_id)]:
            result = embed_dataset_records(db, dataset_id)
            print(f"\n{label} (dataset_id={dataset_id}):")
            print(f"  total_records: {result['total_records']}")
            print(f"  skipped_existing_embedding: {result['skipped_existing_embedding']}")
            print(f"  newly_embedded: {result['newly_embedded']}")

            records = db.query(Record).filter(Record.dataset_id == dataset_id).all()
            missing = [r for r in records if r.embedding is None]
            if missing:
                print(f"  FAIL: {len(missing)} record(s) still have a null embedding")
            else:
                print(f"  PASS: all {len(records)} records have a non-null embedding")
    finally:
        db.close()


if __name__ == "__main__":
    main()
