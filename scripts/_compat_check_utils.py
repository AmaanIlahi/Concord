import sys
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8000"
SAMPLE_DIR = Path(__file__).parent / "sample_data"


def upload(filename: str) -> str:
    path = SAMPLE_DIR / filename
    with open(path, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/datasets",
            files={"file": (path.name, f, "text/csv")},
        )
    if response.status_code != 200:
        print(f"Upload of {filename} failed: {response.status_code}")
        print(response.text)
        sys.exit(1)

    result = response.json()
    print(f"Uploaded {filename} -> dataset_id={result['dataset_id']}")
    print("  schema_mapping:", result["schema_mapping"])
    return result["dataset_id"]


def print_verdict(compatibility_check: dict) -> None:
    signals = compatibility_check["signals"]
    field_overlap = signals["field_overlap"]
    domain = signals["domain_classification"]
    centroid = signals["centroid_distance"]

    signals_passed = sum(
        [field_overlap["passed"], domain["match"], centroid["passed"]]
    )

    print(f"\nVerdict: {compatibility_check['verdict']}")
    print(f"Reasoning: {compatibility_check['reasoning']}")
    print(f"\nSignals passed: {signals_passed}/3")
    print(f"  field_overlap: shared_field_count={field_overlap['shared_field_count']}, "
          f"alignment={field_overlap['alignment']}, passed={field_overlap['passed']}")
    print(f"  domain_classification: domain_a='{domain['domain_a']}', "
          f"domain_b='{domain['domain_b']}', match={domain['match']}")
    print(f"  centroid_distance: cosine_similarity={centroid['cosine_similarity']:.4f}, "
          f"passed={centroid['passed']}")
