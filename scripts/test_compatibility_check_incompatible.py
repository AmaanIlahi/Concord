import requests

from _compat_check_utils import BASE_URL, print_verdict, upload


def main():
    dataset_a_id = upload("products.csv")
    dataset_b_id = upload("restaurants.csv")

    response = requests.post(
        f"{BASE_URL}/match",
        json={"dataset_a_id": dataset_a_id, "dataset_b_id": dataset_b_id},
    )

    print(f"\nPOST /match -> {response.status_code}")

    if response.status_code == 422:
        print_verdict(response.json()["detail"]["compatibility_check"])
    else:
        print_verdict(response.json()["compatibility_check"])

    assert response.status_code == 422, (
        f"Expected 422 (incompatible), got {response.status_code}"
    )
    print("\nPASS: products.csv vs restaurants.csv correctly rejected as incompatible.")


if __name__ == "__main__":
    main()
