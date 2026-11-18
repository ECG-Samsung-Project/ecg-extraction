"""Authenticated, read-only kit lookup."""
from urllib.parse import quote

from api import ApiClient, ApiError
from .config import WatchExtractionConfig


def check_kit(client: ApiClient, kit_name: str) -> dict:
    if not kit_name.strip():
        raise ApiError("Informe o Kit.")
    # request_json supplies Authorization: Bearer <JWT> and rejects offline calls.
    data = client.request_json("GET", f"/api/v1/installer/by-kit/{quote(kit_name.strip(), safe='')}/check")
    if not isinstance(data, dict) or not isinstance(data.get("exists"), bool):
        raise ApiError("Resposta de verificação do Kit inválida.")
    if not data["exists"]:
        return {"exists": False, "participant": "", "context": "", "watches": []}
    participant = data.get("participant")
    watches = data.get("smartwatches") or []
    if (participant is not None and not isinstance(participant, dict)) or not isinstance(watches, list):
        raise ApiError("Resposta de verificação do Kit inválida.")
    code = (participant or {}).get("code") or ""
    if not isinstance(code, str) or any(
        not isinstance(watch, dict) or not isinstance(watch.get("name", ""), str) for watch in watches
    ):
        raise ApiError("Resposta de verificação do Kit inválida.")
    context = ""
    if isinstance(data.get("kit_type"), str):
        try:
            context = WatchExtractionConfig.normalize_collection_context(data["kit_type"])
        except RuntimeError:
            pass
    return {"exists": True, "participant": code, "context": context,
            "watches": list(dict.fromkeys(w["name"] for w in watches if w.get("name")))}
