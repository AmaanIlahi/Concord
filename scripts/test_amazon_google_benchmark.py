import time
from pathlib import Path

import requests

from load_benchmark import load_benchmark_pair

BASE_URL = "http://127.0.0.1:8000"
SAMPLE_LIMIT = 100


def upload(path: Path) -> tuple[str, int]:
    with open(path, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/datasets",
            files={"file": (path.name, f, "text/csv")},
        )
    if response.status_code != 200:
        print(f"Upload of {path.name} failed: {response.status_code}")
        print(response.text)
        raise SystemExit(1)

    result = response.json()
    return result["dataset_id"], result["row_count"]


def timed(label, fn):
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    print(f"{label}: {elapsed:.2f}s")
    return result, elapsed


def main():
    print(f"Loading Amazon-Google Products benchmark (limit={SAMPLE_LIMIT} per side)...")
    amazon_path, google_path = load_benchmark_pair(limit=SAMPLE_LIMIT)

    print(f"\nUploading {amazon_path.name} ...")
    (amazon_id, amazon_count), upload_a_time = timed(
        "Upload Amazon sample", lambda: upload(amazon_path)
    )
    print(f"  dataset_id={amazon_id}  row_count={amazon_count}")

    print(f"\nUploading {google_path.name} ...")
    (google_id, google_count), upload_b_time = timed(
        "Upload Google sample", lambda: upload(google_path)
    )
    print(f"  dataset_id={google_id}  row_count={google_count}")

    def do_match():
        r = requests.post(
            f"{BASE_URL}/match",
            json={"dataset_a_id": amazon_id, "dataset_b_id": google_id},
        )
        return r

    print()
    match_response, match_time = timed("POST /match (compatibility check)", do_match)

    if match_response.status_code != 200:
        print(f"\n/match returned {match_response.status_code}:")
        print(match_response.json())
        return

    match_job_id = match_response.json()["match_job_id"]
    compat = match_response.json()["compatibility_check"]
    print(f"  match_job_id={match_job_id}")
    print(f"  verdict={compat['verdict']}")
    print(f"  reasoning={compat['reasoning']}")

    def do_block():
        return requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/block")

    block_response, block_time = timed("POST /match-jobs/{id}/block", do_block)
    if block_response.status_code != 200:
        print(f"\n/block returned {block_response.status_code}:")
        print(block_response.json())
        return
    candidate_pairs = block_response.json()["candidate_pairs_created"]
    print(f"  candidate_pairs_created={candidate_pairs}")

    def do_score():
        return requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/score")

    score_response, score_time = timed("POST /match-jobs/{id}/score", do_score)
    if score_response.status_code != 200:
        print(f"\n/score returned {score_response.status_code}:")
        print(score_response.json())
        return
    scored_pairs = score_response.json()["scored_pairs"]
    pending_judge_count = sum(1 for p in scored_pairs if p["final_status"] == "pending_judge")
    print(f"  scored_pairs={len(scored_pairs)}  pending_judge={pending_judge_count}")

    def do_judge():
        return requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/judge")

    judge_response, judge_time = timed("POST /match-jobs/{id}/judge", do_judge)
    if judge_response.status_code != 200:
        print(f"\n/judge returned {judge_response.status_code}:")
        print(judge_response.json())
        return
    judged_pairs = judge_response.json()["judged_pairs"]
    print(f"  judged_pairs={judged_pairs}")

    def do_finalize():
        return requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/finalize")

    finalize_response, finalize_time = timed("POST /match-jobs/{id}/finalize", do_finalize)
    if finalize_response.status_code != 200:
        print(f"\n/finalize returned {finalize_response.status_code}:")
        print(finalize_response.json())
        return
    tally = finalize_response.json()["final_status_tally"]
    print(f"  final_status_tally={tally}")

    total_time = (
        upload_a_time + upload_b_time + match_time + block_time
        + score_time + judge_time + finalize_time
    )

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Amazon records uploaded:   {amazon_count}")
    print(f"Google records uploaded:   {google_count}")
    print(f"Candidate pairs (blocking): {candidate_pairs}")
    print(f"Pairs scored:               {len(scored_pairs)}")
    print(f"Pairs sent to LLM judge:    {judged_pairs}")
    print(f"Final status tally:         {tally}")
    print()
    print(f"Upload A time:    {upload_a_time:.2f}s")
    print(f"Upload B time:    {upload_b_time:.2f}s")
    print(f"Match/compat time: {match_time:.2f}s")
    print(f"Blocking time:    {block_time:.2f}s")
    print(f"Scoring time:     {score_time:.2f}s")
    print(f"Judging time:     {judge_time:.2f}s")
    print(f"Finalize time:    {finalize_time:.2f}s")
    print(f"Total pipeline time: {total_time:.2f}s")
    print("\nPipeline completed without errors.")


if __name__ == "__main__":
    main()
