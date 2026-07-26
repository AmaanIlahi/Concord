import requests

from _compat_check_utils import BASE_URL, upload
from app.db import SessionLocal
from app.models import Record


def main():
    dataset_a_id = upload("products.csv")
    dataset_b_id = upload("products_v2.csv")

    match_response = requests.post(
        f"{BASE_URL}/match",
        json={"dataset_a_id": dataset_a_id, "dataset_b_id": dataset_b_id},
    )
    if match_response.status_code != 200:
        print(f"\nPOST /match failed: {match_response.status_code}")
        print(match_response.json())
        return

    match_job_id = match_response.json()["match_job_id"]
    print(f"Match job created: {match_job_id}")

    block_response = requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/block")
    if block_response.status_code != 200:
        print(f"\nBlocking failed: {block_response.status_code}")
        print(block_response.json())
        return
    print(f"Blocking complete: {block_response.json()['candidate_pairs_created']} candidate pairs")

    score_response = requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/score")
    if score_response.status_code != 200:
        print(f"\nScoring failed: {score_response.status_code}")
        print(score_response.json())
        return

    result = score_response.json()
    print(f"Scoring complete: status={result['status']}\n")

    scored_pairs = sorted(
        result["scored_pairs"], key=lambda p: p["hybrid_score"], reverse=True
    )

    db = SessionLocal()
    try:
        record_ids = {p["record_a_id"] for p in scored_pairs} | {p["record_b_id"] for p in scored_pairs}
        names_by_id = {
            str(r.id): (r.canonical_json or {}).get("name", "?")
            for r in db.query(Record).filter(Record.id.in_(record_ids)).all()
        }
    finally:
        db.close()

    print(f"{'record_a':<22} {'record_b':<22} {'blocking':>9} {'string':>7} {'hybrid':>7} {'status':<15}")
    for pair in scored_pairs:
        name_a = names_by_id.get(pair["record_a_id"], "?")
        name_b = names_by_id.get(pair["record_b_id"], "?")
        print(
            f"{name_a:<22} {name_b:<22} "
            f"{pair['blocking_score']:>9.4f} {pair['string_score']:>7.4f} "
            f"{pair['hybrid_score']:>7.4f} {pair['final_status']:<15}"
        )

    status_counts = {}
    for pair in scored_pairs:
        status_counts[pair["final_status"]] = status_counts.get(pair["final_status"], 0) + 1
    print("\nStatus counts:", status_counts)


if __name__ == "__main__":
    main()
