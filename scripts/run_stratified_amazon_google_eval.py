import time
from pathlib import Path

import requests

from load_benchmark import load_stratified_sample
from app.db import SessionLocal
from app.services.bulk_embedding import embed_dataset_records

BASE_URL = "http://127.0.0.1:8000"
REQUEST_TIMEOUT = 3600
DATASET_PAIR_NAME = "amazon_google_stratified_150"

POSITIVE_COUNT = 150
NEGATIVE_COUNT = 150


def upload(path: Path) -> tuple[str, int]:
    with open(path, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/datasets",
            files={"file": (path.name, f, "text/csv")},
            timeout=REQUEST_TIMEOUT,
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
    print(
        f"Building stratified Amazon-Google sample "
        f"({POSITIVE_COUNT} positives + {NEGATIVE_COUNT} negatives)..."
    )
    amazon_path, google_path, gold_path = load_stratified_sample(
        positive_count=POSITIVE_COUNT, negative_count=NEGATIVE_COUNT
    )
    print(f"  gold file scoped to sample: {gold_path.name}")

    print(f"\nUploading {amazon_path.name} ...")
    (amazon_id, amazon_count), upload_a_time = timed(
        "Upload Amazon (stratified sample)", lambda: upload(amazon_path)
    )
    print(f"  dataset_id={amazon_id}  row_count={amazon_count}")

    print(f"\nUploading {google_path.name} ...")
    (google_id, google_count), upload_b_time = timed(
        "Upload Google (stratified sample)", lambda: upload(google_path)
    )
    print(f"  dataset_id={google_id}  row_count={google_count}")

    def do_bulk_embed():
        db = SessionLocal()
        try:
            result_a = embed_dataset_records(db, amazon_id)
            result_b = embed_dataset_records(db, google_id)
            return result_a, result_b
        finally:
            db.close()

    print()
    (embed_result_a, embed_result_b), embed_time = timed(
        "Bulk embedding (both datasets)", do_bulk_embed
    )
    print(f"  Amazon: total={embed_result_a['total_records']} "
          f"skipped={embed_result_a['skipped_existing_embedding']} "
          f"newly_embedded={embed_result_a['newly_embedded']}")
    print(f"  Google: total={embed_result_b['total_records']} "
          f"skipped={embed_result_b['skipped_existing_embedding']} "
          f"newly_embedded={embed_result_b['newly_embedded']}")

    def do_match():
        return requests.post(
            f"{BASE_URL}/match",
            json={"dataset_a_id": amazon_id, "dataset_b_id": google_id},
            timeout=REQUEST_TIMEOUT,
        )

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

    if compat["verdict"] != "compatible":
        print("\nDatasets deemed incompatible, stopping before blocking.")
        return

    def do_block():
        return requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/block", timeout=REQUEST_TIMEOUT)

    block_response, block_time = timed("POST /match-jobs/{id}/block", do_block)
    if block_response.status_code != 200:
        print(f"\n/block returned {block_response.status_code}:")
        print(block_response.json())
        return
    candidate_pairs = block_response.json()["candidate_pairs_created"]
    print(f"  candidate_pairs_created={candidate_pairs}")

    def do_score():
        return requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/score", timeout=REQUEST_TIMEOUT)

    score_response, score_time = timed("POST /match-jobs/{id}/score", do_score)
    if score_response.status_code != 200:
        print(f"\n/score returned {score_response.status_code}:")
        print(score_response.json())
        return
    scored_pairs = score_response.json()["scored_pairs"]
    pending_judge_count = sum(1 for p in scored_pairs if p["final_status"] == "pending_judge")
    print(f"  scored_pairs={len(scored_pairs)}  pending_judge={pending_judge_count}")

    def do_judge():
        return requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/judge", timeout=REQUEST_TIMEOUT)

    judge_response, judge_time = timed("POST /match-jobs/{id}/judge", do_judge)
    if judge_response.status_code != 200:
        print(f"\n/judge returned {judge_response.status_code}:")
        print(judge_response.json())
        return
    judged_pairs = judge_response.json()["judged_pairs"]
    print(f"  judged_pairs={judged_pairs}")

    def do_finalize():
        return requests.post(f"{BASE_URL}/match-jobs/{match_job_id}/finalize", timeout=REQUEST_TIMEOUT)

    finalize_response, finalize_time = timed("POST /match-jobs/{id}/finalize", do_finalize)
    if finalize_response.status_code != 200:
        print(f"\n/finalize returned {finalize_response.status_code}:")
        print(finalize_response.json())
        return
    tally = finalize_response.json()["final_status_tally"]
    print(f"  final_status_tally={tally}")

    def do_eval():
        return requests.post(
            f"{BASE_URL}/eval",
            json={"match_job_id": match_job_id, "dataset_pair_name": DATASET_PAIR_NAME},
            timeout=REQUEST_TIMEOUT,
        )

    eval_response, eval_time = timed("POST /eval", do_eval)
    if eval_response.status_code != 200:
        print(f"\n/eval returned {eval_response.status_code}:")
        print(eval_response.json())
        return
    eval_result = eval_response.json()

    total_time = (
        upload_a_time + upload_b_time + embed_time + match_time + block_time
        + score_time + judge_time + finalize_time + eval_time
    )

    print("\n" + "=" * 70)
    print("PIPELINE SUMMARY (stratified sample)")
    print("=" * 70)
    print(f"Amazon records uploaded:    {amazon_count}")
    print(f"Google records uploaded:    {google_count}")
    print(f"Candidate pairs (blocking): {candidate_pairs}")
    print(f"Pairs scored:               {len(scored_pairs)}")
    print(f"Pairs sent to LLM judge:    {judged_pairs}")
    print(f"Final status tally:         {tally}")
    print()
    print(f"Upload A time:     {upload_a_time:.2f}s")
    print(f"Upload B time:     {upload_b_time:.2f}s")
    print(f"Bulk embed time:   {embed_time:.2f}s")
    print(f"Match/compat time: {match_time:.2f}s")
    print(f"Blocking time:     {block_time:.2f}s")
    print(f"Scoring time:      {score_time:.2f}s")
    print(f"Judging time:      {judge_time:.2f}s")
    print(f"Finalize time:     {finalize_time:.2f}s")
    print(f"Eval time:         {eval_time:.2f}s")
    print(f"Total pipeline time: {total_time:.2f}s")

    print("\n" + "=" * 70)
    print("EVAL RESULTS: matching_accuracy")
    print("=" * 70)
    ma = eval_result["matching_accuracy"]
    if ma["string_similarity_available"] is False:
        print("*** WARNING: string_similarity_available=False for this job ***")
        print("*** Field alignment was empty; hybrid_score fell back to blocking_score alone. ***")
        print("*** Precision/recall below reflect a degraded signal, not a normal run. ***\n")
    print(f"gold_pair_count (scoped to sample): {ma['gold_pair_count']}")
    print(f"predicted_pair_count: {ma['predicted_pair_count']}")
    print(f"true_positives:       {ma['true_positives']}")
    print(f"false_positives:      {ma['false_positives']}")
    print(f"false_negatives:      {ma['false_negatives']}")
    print(f"precision: {ma['precision']:.4f}")
    print(f"recall:    {ma['recall']:.4f}")
    print(f"f1:        {ma['f1']:.4f}")
    print(f"string_similarity_available: {ma['string_similarity_available']}")

    print("\n" + "=" * 70)
    print("EVAL RESULTS: confidence calibration")
    print("=" * 70)
    for bucket, stats in eval_result["calibration"].items():
        acc = f"{stats['accuracy']:.4f}" if stats["accuracy"] is not None else "n/a"
        print(f"  {bucket:<8} count={stats['count']:<6} accuracy={acc}")

    print("\n" + "=" * 70)
    print("EVAL RESULTS: cost efficiency")
    print("=" * 70)
    ce = eval_result["cost_efficiency"]
    print(f"total_candidate_pairs:   {ce['total_candidate_pairs']}")
    print(f"resolved_by_hybrid_alone: {ce['resolved_by_hybrid_alone']} ({ce['hybrid_only_fraction']:.1%})")
    print(f"escalated_to_judge:       {ce['escalated_to_judge']} ({ce['escalated_fraction']:.1%})")

    print("\nStratified benchmark pipeline + eval completed without errors.")


if __name__ == "__main__":
    main()
