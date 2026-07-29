import requests

from _compat_check_utils import BASE_URL, upload


def main():
    dataset_a_id = upload("products.csv")
    dataset_b_id = upload("products_v3.csv")

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
    tally = finalize_result["final_status_tally"]
    print(f"Finalize complete: status={finalize_result['status']}")
    print(f"Final status tally: {tally}\n")

    accepted_with_conflicts = requests.get(
        f"{BASE_URL}/matches/{match_job_id}", params={"status": "accepted_with_conflicts"}
    ).json()

    assert accepted_with_conflicts["count"] >= 1, (
        "Expected at least one match in accepted_with_conflicts, got "
        f"{accepted_with_conflicts['count']}. Full tally: {tally}"
    )
    print(f"PASS: {accepted_with_conflicts['count']} match(es) landed in accepted_with_conflicts\n")

    price_conflict_match = None
    for match in accepted_with_conflicts["matches"]:
        if any(c["conflict_type"] in ("contradiction", "unit_mismatch")
               and "price" in c["field_name"].lower() for c in match["conflicts"]):
            price_conflict_match = match
            break

    assert price_conflict_match is not None, (
        "Expected at least one accepted_with_conflicts match to have a price-related conflict, "
        f"but none did. Matches: {accepted_with_conflicts['matches']}"
    )

    name_a = (price_conflict_match["record_a"]["canonical_json"] or {}).get("name", "?")
    name_b = (price_conflict_match["record_b"]["canonical_json"] or {}).get("name", "?")

    print(f"PASS: found price-conflict match: {name_a}  <->  {name_b}")
    print(f"  final_status: {price_conflict_match['final_status']}")
    if price_conflict_match["llm_verdict"]:
        print(f"  llm_verdict.reasoning: {price_conflict_match['llm_verdict']['reasoning']!r}")
    else:
        print("  llm_verdict: none (pair auto-accepted by hybrid scoring before reaching the "
              "judge; conflict was caught by the post-hoc field-diff check in finalize)")
    print("  conflicts:")
    for c in price_conflict_match["conflicts"]:
        print(f"    - {c['field_name']}: '{c['value_a']}' vs '{c['value_b']}' ({c['conflict_type']})")


if __name__ == "__main__":
    main()
