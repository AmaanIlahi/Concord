import requests

from _compat_check_utils import BASE_URL, upload


def print_match_summary(match: dict) -> None:
    name_a = (match["record_a"]["canonical_json"] or {}).get("name", "?") if match["record_a"] else "?"
    name_b = (match["record_b"]["canonical_json"] or {}).get("name", "?") if match["record_b"] else "?"
    print(f"  {name_a}  <->  {name_b}")
    print(f"    blocking_score={match['blocking_score']:.4f}  hybrid_score={match['hybrid_score']}")
    print(f"    final_status={match['final_status']}")
    if match["llm_verdict"]:
        v = match["llm_verdict"]
        print(f"    llm_verdict: match={v.get('match')} confidence={v.get('confidence')} "
              f"reasoning={v.get('reasoning')!r}")
    if match["conflicts"]:
        print("    conflicts:")
        for c in match["conflicts"]:
            print(f"      - {c['field_name']}: '{c['value_a']}' vs '{c['value_b']}' ({c['conflict_type']})")


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
    print(f"Scoring complete: {len(score_response.json()['scored_pairs'])} pairs scored")

    judge_response = requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/judge")
    print(f"Judging complete: {judge_response.json()['judged_pairs']} pairs judged")

    finalize_response = requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/finalize")
    if finalize_response.status_code != 200:
        print(f"\nFinalize failed: {finalize_response.status_code}")
        print(finalize_response.json())
        return

    finalize_result = finalize_response.json()
    print(f"Finalize complete: status={finalize_result['status']}")
    print(f"Final status tally: {finalize_result['final_status_tally']}\n")

    print("=" * 70)
    print("GET /matches/{job_id} (unfiltered)")
    print("=" * 70)
    all_matches = requests.get(f"{BASE_URL}/matches/{match_job_id}").json()
    print(f"count={all_matches['count']}\n")
    for m in all_matches["matches"]:
        print_match_summary(m)
        print()

    for status in ["accepted_with_conflicts", "flagged_for_review"]:
        print("=" * 70)
        print(f"GET /matches/{{job_id}}?status={status}")
        print("=" * 70)
        filtered = requests.get(f"{BASE_URL}/matches/{match_job_id}", params={"status": status}).json()
        print(f"count={filtered['count']}\n")
        for m in filtered["matches"]:
            print_match_summary(m)
            print()

    print("=" * 70)
    print("Final tally across all matches in this job:")
    print("=" * 70)
    print(finalize_result["final_status_tally"])


if __name__ == "__main__":
    main()
