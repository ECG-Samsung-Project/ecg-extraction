import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


def load_base_url() -> str:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    return validate_base_url(os.getenv("ECG_API_BASE_URL", "https://ecg.uea.edu.br"))


def validate_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("ECG_API_BASE_URL deve ser uma URL HTTPS válida.")
    return value
