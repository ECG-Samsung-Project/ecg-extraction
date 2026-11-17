import sys
from typing import Any

import requests

from .config import load_base_url, validate_base_url
from .models import AuthSession, OfflineSession, User

AUTH_API_ENDPOINT = "/api/v1/auth/login"
USER_AGENT = f"ECGExtraction/1.0 ({sys.platform})"


class ApiError(Exception):
    """An API failure with a message safe to display."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class AuthenticationError(ApiError):
    """Credentials were rejected or an API session has expired."""


class ApiClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = validate_base_url(base_url) if base_url is not None else load_base_url()
        self.session: AuthSession | None = None
        self.offline_session: OfflineSession | None = None

    def enter_offline(self, operator_name: str) -> OfflineSession:
        if not operator_name.strip():
            raise ApiError("Informe o nome do operador.")
        self.session = None
        self.offline_session = OfflineSession(operator_name)
        return self.offline_session

    def _request(self, method: str, path: str, *, payload: Any = None,
                 token: str | None = None) -> Any:
        # Accept API-relative paths only; never forward credentials to another host.
        if (not path.startswith("/") or path.startswith("//") or "\\" in path
                or ".." in path or "#" in path or "?" in path):
            raise ValueError("Use um caminho relativo da API sem query ou fragmento.")
        headers = {"Accept": "*/*", "Content-Type": "application/json",
                   "User-Agent": USER_AGENT}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = requests.request(
                method, self.base_url + path, json=payload, headers=headers,
                timeout=(5, 20), allow_redirects=False,
            )
        except requests.Timeout:
            raise ApiError("O servidor demorou para responder. Tente novamente.") from None
        except requests.RequestException:
            raise ApiError("Não foi possível conectar à API. Verifique sua conexão.") from None
        with response:
            if not 200 <= response.status_code < 300:
                detail = ""
                try:
                    body = response.json()
                    if isinstance(body, dict) and isinstance(body.get("detail"), str):
                        detail = body["detail"]
                except ValueError:
                    pass
                # Never echo submitted credentials or tokens in UI error messages.
                secrets = [token]
                if isinstance(payload, dict):
                    secrets.extend(payload.values())
                for secret in secrets:
                    if isinstance(secret, str) and secret:
                        detail = detail.replace(secret, "[omitido]")
                detail = " ".join(detail.split())[:300]
            if response.status_code == 401:
                raise AuthenticationError("Autenticação inválida ou sessão expirada.", 401)
            if response.status_code == 403:
                raise ApiError("Acesso negado pelo servidor (HTTP 403)." +
                               (f" {detail}" if detail else ""), 403)
            if response.status_code == 429:
                raise ApiError("Muitas tentativas. Aguarde antes de tentar novamente.", 429)
            if not 200 <= response.status_code < 300:
                raise ApiError(f"A API não concluiu a solicitação (HTTP {response.status_code})." +
                               (f" {detail}" if detail else ""), response.status_code)
            if response.status_code == 204:
                return None
            try:
                return response.json()
            except ValueError:
                raise ApiError("O servidor retornou uma resposta inválida.") from None

    def login(self, username: str, password: str) -> AuthSession:
        self.session = None
        self.offline_session = None
        if not username or not password:
            raise ApiError("Informe o usuário e a senha.")
        try:
            data = self._request("POST", AUTH_API_ENDPOINT, payload={
                "username": username, "password": password,
            })
        except AuthenticationError:
            raise AuthenticationError("Usuário ou senha inválidos.", 401) from None
        fields = ("access_token", "refresh_token", "token_type", "user_id",
                  "username", "full_name", "role")
        if (not isinstance(data, dict)
                or any(not isinstance(data.get(key), str) or not data[key].strip()
                       for key in fields)
                or data["token_type"].lower() != "bearer"):
            raise ApiError("O servidor retornou dados de autenticação inválidos.")
        self.session = AuthSession(
            access_token=data["access_token"], refresh_token=data["refresh_token"],
            token_type="bearer", user=User(**{key: data[key] for key in fields[3:]}),
        )
        return self.session

    def request_json(self, method: str, path: str, *, payload: Any = None) -> Any:
        if self.offline_session is not None:
            raise AuthenticationError("Modo offline: entre com login para acessar a API.")
        if self.session is None:
            raise AuthenticationError("Faça login para acessar a API.")
        try:
            return self._request(method, path, payload=payload, token=self.session.access_token)
        except AuthenticationError:
            self.session = None
            raise
