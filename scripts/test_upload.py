import json
import sys
from pathlib import Path

import requests

BASE_URL = "http://127.0.0.1:8000"
SAMPLE_FILE = Path(__file__).parent / "sample_data" / "products.csv"


def main():
    with open(SAMPLE_FILE, "rb") as f:
        response = requests.post(
            f"{BASE_URL}/datasets",
            files={"file": (SAMPLE_FILE.name, f, "text/csv")},
        )

    if response.status_code != 200:
        print(f"Upload failed: {response.status_code}")
        print(response.text)
        sys.exit(1)

    result = response.json()
    print("Dataset ID:", result["dataset_id"])
    print("Row count:", result["row_count"])
    print("\nInferred schema mapping:")
    print(json.dumps(result["schema_mapping"], indent=2))

    detail = requests.get(f"{BASE_URL}/datasets/{result['dataset_id']}").json()
    print("\nSample canonical records:")
    for rec in detail["sample_records"]:
        print(json.dumps(rec["canonical_json"], indent=2))


if __name__ == "__main__":
    main()
