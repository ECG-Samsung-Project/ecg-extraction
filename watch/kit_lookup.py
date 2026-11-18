"""Compatibility wrapper for watch kit identification."""
from api import ApiClient
from api.kit import check_kit_devices


def check_kit(client: ApiClient, kit_name: str) -> dict:
    result = check_kit_devices(client, kit_name, "watch")
    result["watches"] = result.pop("devices")
    return result
