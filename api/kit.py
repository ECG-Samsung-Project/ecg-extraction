"""Read-only kit identification shared by local extraction screens."""
from urllib.parse import quote

from .client import ApiClient, ApiError


def check_kit_devices(client: ApiClient, kit_name: str, device_collection: str) -> dict:
    if device_collection not in {"mobile", "watch"}:
        raise ValueError("Unsupported kit device collection")
    if not kit_name.strip():
        raise ApiError("Informe o Kit.")
    # The existing client adds the session JWT and rejects offline requests.
    data = client.request_json("GET", f"/api/v1/installer/by-kit/{quote(kit_name.strip(), safe='')}/check")
    if not isinstance(data, dict) or not isinstance(data.get("exists"), bool):
        raise ApiError("Resposta de verificação do Kit inválida.")
    if not data["exists"]:
        return {"exists": False, "participant": "", "context": "", "devices": []}
    participant = data.get("participant")
    response_field = {"mobile": "smartphones", "watch": "smartwatches"}[device_collection]
    devices = data.get(response_field)
    if devices is None:
        devices = []
    if (participant is not None and not isinstance(participant, dict)) or not isinstance(devices, list):
        raise ApiError("Resposta de verificação do Kit inválida.")
    code = (participant or {}).get("code") or ""
    if not isinstance(code, str) or any(
        not isinstance(device, dict) or not isinstance(device.get("name", ""), str) for device in devices
    ):
        raise ApiError("Resposta de verificação do Kit inválida.")
    kit_type = data.get("kit_type")
    normalized = kit_type.strip().lower().replace("-", "_").replace(" ", "_") if isinstance(kit_type, str) else ""
    context = {"fl": "free_living", "freeliving": "free_living", "free_living": "free_living",
               "ic": "in_clinic", "inclinic": "in_clinic", "in_clinic": "in_clinic"}.get(normalized, "")
    return {"exists": True, "participant": code, "context": context,
            "devices": list(dict.fromkeys(d["name"] for d in devices if d.get("name")))}
