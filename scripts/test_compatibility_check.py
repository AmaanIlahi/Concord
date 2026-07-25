import json
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


def main():
    dataset_a_id = upload("products.csv")
    dataset_b_id = upload("products_v2.csv")

    response = requests.post(
        f"{BASE_URL}/match",
        json={"dataset_a_id": dataset_a_id, "dataset_b_id": dataset_b_id},
    )

    print(f"\nPOST /match -> {response.status_code}")
    body = response.json()
    print(json.dumps(body, indent=2))


if __name__ == "__main__":
    main()
