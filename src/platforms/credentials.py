from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OAuthCredentials:
    client_id: str
    client_secret: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)
