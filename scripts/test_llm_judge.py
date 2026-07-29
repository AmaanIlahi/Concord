import requests

from _compat_check_utils import BASE_URL, upload
from app.db import SessionLocal
from app.models import Conflict, Match, Record


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
    print(f"Blocking complete: {block_response.json()['candidate_pairs_created']} candidate pairs")

    score_response = requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/score")
    scored_pairs = score_response.json()["scored_pairs"]
    pending_judge_count = sum(1 for p in scored_pairs if p["final_status"] == "pending_judge")
    print(f"Scoring complete: {pending_judge_count} pairs sent to pending_judge")

    judge_response = requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/judge")
    if judge_response.status_code != 200:
        print(f"\nJudging failed: {judge_response.status_code}")
        print(judge_response.json())
        return

    judge_result = judge_response.json()
    print(f"Judging complete: status={judge_result['status']}, judged_pairs={judge_result['judged_pairs']}\n")

    db = SessionLocal()
    try:
        matches = (
            db.query(Match)
            .filter(Match.job_id == match_job_id, Match.llm_verdict.isnot(None))
            .order_by(Match.hybrid_score.desc())
            .all()
        )

        record_ids = {m.record_a_id for m in matches} | {m.record_b_id for m in matches}
        records_by_id = {r.id: r for r in db.query(Record).filter(Record.id.in_(record_ids)).all()}

        for match in matches:
            record_a = records_by_id[match.record_a_id]
            record_b = records_by_id[match.record_b_id]
            name_a = (record_a.canonical_json or {}).get("name", "?")
            name_b = (record_b.canonical_json or {}).get("name", "?")
            verdict = match.llm_verdict

            print(f"{name_a}  <->  {name_b}")
            print(f"  hybrid_score={match.hybrid_score:.4f}")
            print(f"  match={verdict['match']}  confidence={verdict['confidence']}")
            print(f"  reasoning: {verdict['reasoning']}")

            conflicts = db.query(Conflict).filter(Conflict.match_id == match.id).all()
            if conflicts:
                print("  conflicts:")
                for c in conflicts:
                    print(f"    - {c.field_name}: '{c.value_a}' vs '{c.value_b}' ({c.conflict_type})")
            else:
                print("  conflicts: none")
            print()

        needs_review = (
            db.query(Match)
            .filter(Match.job_id == match_job_id, Match.final_status == "needs_manual_review")
            .all()
        )
        if needs_review:
            print(f"{len(needs_review)} pair(s) marked needs_manual_review (LLM judge failed after retry):")
            for m in needs_review:
                print(f"  match_id={m.id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
