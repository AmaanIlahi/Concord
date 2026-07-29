"""Diagnoses where recall is lost for a given match job, by checking each
false-negative gold pair against three stages: did blocking even produce a
candidate row, what hybrid_score/final_status did it get if so, and did the
judge (if reached) call it a non-match."""
import csv
import sys
from pathlib import Path

from app.db import SessionLocal
from app.models import Match, MatchJob, Record

BENCHMARK_DIR = Path(__file__).parent / "sample_data" / "benchmarks" / "amazon_google"


def load_gold_pairs(gold_csv_path: Path) -> set[tuple[str, str]]:
    with open(gold_csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return {(row["idAmazon"], row["idGoogleBase"]) for row in reader}


def main(match_job_id: str, gold_csv_path: Path):
    db = SessionLocal()
    try:
        match_job = db.get(MatchJob, match_job_id)
        if match_job is None:
            print(f"Match job {match_job_id} not found")
            return

        gold_pairs = load_gold_pairs(gold_csv_path)
        print(f"Gold pairs (scoped to this sample): {len(gold_pairs)}")

        records_a = db.query(Record).filter(Record.dataset_id == match_job.dataset_a_id).all()
        records_b = db.query(Record).filter(Record.dataset_id == match_job.dataset_b_id).all()

        record_id_by_source_id_a = {(r.raw_json or {}).get("id"): r.id for r in records_a}
        record_id_by_source_id_b = {(r.raw_json or {}).get("id"): r.id for r in records_b}

        matches = db.query(Match).filter(Match.job_id == match_job_id).all()
        match_by_pair = {(m.record_a_id, m.record_b_id): m for m in matches}

        # Reproduce eval_matching's predicted-match rule to find the actual false negatives.
        predicted_match_statuses = {"auto_accepted", "accepted_with_conflicts"}

        def is_predicted_match(m: Match) -> bool:
            if m.final_status in predicted_match_statuses:
                return True
            if m.llm_verdict and m.llm_verdict.get("match") is True:
                return True
            return False

        no_candidate_pair = []
        auto_rejected_before_judge = []
        reached_judge_but_missed = []
        actually_found = []
        source_ids_not_in_sample = []

        for source_id_a, source_id_b in gold_pairs:
            record_id_a = record_id_by_source_id_a.get(source_id_a)
            record_id_b = record_id_by_source_id_b.get(source_id_b)

            if record_id_a is None or record_id_b is None:
                source_ids_not_in_sample.append((source_id_a, source_id_b))
                continue

            match = match_by_pair.get((record_id_a, record_id_b))

            if match is None:
                no_candidate_pair.append((source_id_a, source_id_b))
                continue

            if is_predicted_match(match):
                actually_found.append((source_id_a, source_id_b, match))
                continue

            if match.llm_verdict is not None:
                reached_judge_but_missed.append((source_id_a, source_id_b, match))
            else:
                auto_rejected_before_judge.append((source_id_a, source_id_b, match))

        print(f"\nGold pairs with a source record missing from this sample: {len(source_ids_not_in_sample)}")

        total_checked = len(gold_pairs) - len(source_ids_not_in_sample)
        print(f"Gold pairs actually evaluable in this sample: {total_checked}")

        print(f"\n=== Category 1: No candidate pair from blocking ===")
        print(f"Count: {len(no_candidate_pair)}")
        for source_id_a, source_id_b in no_candidate_pair[:5]:
            print(f"  Amazon={source_id_a}  Google={source_id_b}")
        if len(no_candidate_pair) > 5:
            print(f"  ... and {len(no_candidate_pair) - 5} more")

        print(f"\n=== Category 2: Candidate pair existed, cut off before judge (auto_rejected/pending_judge with no verdict) ===")
        print(f"Count: {len(auto_rejected_before_judge)}")
        for source_id_a, source_id_b, m in auto_rejected_before_judge[:10]:
            print(f"  Amazon={source_id_a}  Google={source_id_b}  hybrid_score={m.hybrid_score:.4f}  "
                  f"blocking_score={m.blocking_score:.4f}  final_status={m.final_status}")
        if len(auto_rejected_before_judge) > 10:
            print(f"  ... and {len(auto_rejected_before_judge) - 10} more")

        print(f"\n=== Category 3: Reached the judge, judge said match=false (or low confidence) ===")
        print(f"Count: {len(reached_judge_but_missed)}")
        for source_id_a, source_id_b, m in reached_judge_but_missed[:10]:
            v = m.llm_verdict
            print(f"  Amazon={source_id_a}  Google={source_id_b}  hybrid_score={m.hybrid_score:.4f}  "
                  f"judge_match={v.get('match')}  confidence={v.get('confidence')}  "
                  f"reasoning={v.get('reasoning', '')[:100]!r}")
        if len(reached_judge_but_missed) > 10:
            print(f"  ... and {len(reached_judge_but_missed) - 10} more")

        print(f"\n=== Correctly found (for sanity check against eval's true_positives) ===")
        print(f"Count: {len(actually_found)}")

        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"Total gold pairs:                          {len(gold_pairs)}")
        print(f"  - Not evaluable (record missing):        {len(source_ids_not_in_sample)}")
        print(f"  - Correctly found (true positives):      {len(actually_found)}")
        print(f"  - Lost at blocking (no candidate pair):  {len(no_candidate_pair)}")
        print(f"  - Lost at hybrid scoring (cut before judge): {len(auto_rejected_before_judge)}")
        print(f"  - Lost at judge (judge said no/low-conf):    {len(reached_judge_but_missed)}")
        total_lost = len(no_candidate_pair) + len(auto_rejected_before_judge) + len(reached_judge_but_missed)
        print(f"  - Total false negatives:                 {total_lost}")

    finally:
        db.close()


if __name__ == "__main__":
    match_job_id = sys.argv[1]
    gold_path = BENCHMARK_DIR / "gold_stratified_150.csv"
    main(match_job_id, gold_path)
