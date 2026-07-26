import requests

from _compat_check_utils import BASE_URL, print_verdict, upload


def main():
    dataset_a_id = upload("products.csv")
    dataset_b_id = upload("products_v2.csv")

    response = requests.post(
        f"{BASE_URL}/match",
        json={"dataset_a_id": dataset_a_id, "dataset_b_id": dataset_b_id},
    )

    print(f"\nPOST /match -> {response.status_code}")
    print_verdict(response.json()["compatibility_check"])


if __name__ == "__main__":
    main()
