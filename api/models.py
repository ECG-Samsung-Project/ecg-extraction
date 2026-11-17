from dataclasses import dataclass, field


@dataclass(frozen=True)
class User:
    user_id: str
    username: str
    full_name: str
    role: str


@dataclass(frozen=True)
class AuthSession:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    token_type: str
    user: User


@dataclass(frozen=True)
class OfflineSession:
    operator_name: str
