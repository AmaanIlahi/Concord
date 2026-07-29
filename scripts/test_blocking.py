import time

import requests

from _compat_check_utils import BASE_URL, upload


def main():
    dataset_a_id = upload("products.csv")
    dataset_b_id = upload("products_v2.csv")

    print("\nChecking same-dataset_id rejection...")
    same_id_response = requests.post(
        f"{BASE_URL}/match",
        json={"dataset_a_id": dataset_a_id, "dataset_b_id": dataset_a_id},
    )
    assert same_id_response.status_code == 422, (
        f"Expected 422 for same dataset_id, got {same_id_response.status_code}"
    )
    print(f"  PASS: same dataset_id rejected with 422: {same_id_response.json()['detail']}")

    match_response = requests.post(
        f"{BASE_URL}/match",
        json={"dataset_a_id": dataset_a_id, "dataset_b_id": dataset_b_id},
    )
    if match_response.status_code != 200:
        print(f"\nPOST /match failed: {match_response.status_code}")
        print(match_response.json())
        return

    match_job_id = match_response.json()["match_job_id"]
    print(f"\nMatch job created: {match_job_id} (status={match_response.json()['status']})")

    print("\nRunning blocking step...")
    start = time.perf_counter()
    block_response = requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/block")
    elapsed = time.perf_counter() - start

    if block_response.status_code != 200:
        print(f"Blocking failed: {block_response.status_code}")
        print(block_response.json())
        return

    block_result = block_response.json()
    print(f"Blocking complete in {elapsed:.2f}s")
    print(f"  status: {block_result['status']}")
    print(f"  candidate_pairs_created: {block_result['candidate_pairs_created']}")

    matches_response = requests.get(f"{BASE_URL}/matches/{match_job_id}")
    if matches_response.status_code == 200:
        matches = matches_response.json()
    else:
        print("\n(GET /matches/{job_id} not implemented yet, querying DB directly for top pairs)")
        matches = None

    if matches is None:
        from app.db import SessionLocal
        from app.models import Match

        db = SessionLocal()
        try:
            rows = (
                db.query(Match)
                .filter(Match.job_id == match_job_id)
                .order_by(Match.blocking_score.desc())
                .limit(5)
                .all()
            )
            print("\nTop candidate pairs by blocking_score:")
            for m in rows:
                print(f"  record_a={m.record_a_id} record_b={m.record_b_id} "
                      f"blocking_score={m.blocking_score:.4f}")
        finally:
            db.close()


if __name__ == "__main__":
    main()
