from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx

from src.config import get_settings
from src.services.oauth_pkce import store_pkce_verifier
from src.db.models import Platform
from src.platforms.base import CategoryResult, PlatformAdapter, PlatformStatus, StreamInfo
from src.platforms.category_utils import clean_game_query, rank_categories, search_query_variants
from src.platforms.credentials import OAuthCredentials

KICK_AUTH = "https://id.kick.com"
KICK_API = "https://api.kick.com/public/v1"
KICK_SCOPES = "user:read channel:read channel:write"


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class KickAdapter(PlatformAdapter):
    platform = Platform.KICK

    def _headers(self, access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    def get_oauth_url(self, state: str, creds: OAuthCredentials) -> str | None:
        if not creds.configured:
            return None
        verifier, challenge = _pkce_pair()
        store_pkce_verifier(state, verifier)
        redirect = f"{get_settings().oauth_callback_base}/kick"
        params = urlencode(
            {
                "response_type": "code",
                "client_id": creds.client_id,
                "redirect_uri": redirect,
                "scope": KICK_SCOPES,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{KICK_AUTH}/oauth/authorize?{params}"

    async def exchange_code(
        self,
        code: str,
        creds: OAuthCredentials,
        *,
        code_verifier: str | None = None,
        device_id: str | None = None,
        oauth_state: str | None = None,
    ) -> dict:
        if not code_verifier:
            raise ValueError("Kick OAuth requires PKCE code_verifier")
        redirect = f"{get_settings().oauth_callback_base}/kick"
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{KICK_AUTH}/oauth/token",
                data={
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect,
                    "code_verifier": code_verifier,
                },
            )
            r.raise_for_status()
            data = r.json()
            channel = await self._get_channel(data["access_token"])
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in"),
                "channel_id": str(channel.get("broadcaster_user_id", channel.get("id", ""))),
                "channel_name": channel.get("slug", ""),
            }

    async def refresh_access_token(
        self, refresh_token: str, creds: OAuthCredentials, *, device_id: str | None = None
    ) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{KICK_AUTH}/oauth/token",
                data={
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", refresh_token),
                "expires_in": data.get("expires_in"),
            }

    async def _get_channel(self, access_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{KICK_API}/channels", headers=self._headers(access_token))
            r.raise_for_status()
            payload = r.json()
            if isinstance(payload, dict) and "data" in payload:
                items = payload["data"]
                return items[0] if isinstance(items, list) and items else payload["data"]
            return payload

    async def get_channel_title(
        self, access_token: str, channel_id: str, creds: OAuthCredentials
    ) -> str | None:
        ch = await self._get_channel(access_token)
        return ch.get("stream_title") or (ch.get("stream") or {}).get("title")

    async def search_categories(
        self, query: str, access_token: str, creds: OAuthCredentials
    ) -> list[CategoryResult]:
        query = clean_game_query(query)
        seen: set[str] = set()
        merged: list[CategoryResult] = []
        async with httpx.AsyncClient() as client:
            for variant in search_query_variants(query):
                r = await client.get(
                    f"{KICK_API}/categories",
                    params={"q": variant},
                    headers=self._headers(access_token),
                )
                r.raise_for_status()
                items = r.json().get("data", r.json())
                if not isinstance(items, list):
                    items = items.get("categories", []) if isinstance(items, dict) else []
                for c in items:
                    cid = str(c["id"])
                    if cid in seen:
                        continue
                    seen.add(cid)
                    merged.append(CategoryResult(id=cid, name=c.get("name", "")))
        return rank_categories(query, merged)[:10]

    async def update_stream(
        self,
        access_token: str,
        channel_id: str,
        creds: OAuthCredentials,
        *,
        title: str | None = None,
        category_id: str | None = None,
    ) -> None:
        body: dict = {}
        if title is not None:
            body["stream_title"] = title
        if category_id is not None:
            body["category_id"] = int(category_id)
        if not body:
            return
        async with httpx.AsyncClient() as client:
            r = await client.patch(
                f"{KICK_API}/channels",
                headers={**self._headers(access_token), "Content-Type": "application/json"},
                json=body,
            )
            r.raise_for_status()

    async def get_stream_info(
        self, access_token: str, channel_id: str, creds: OAuthCredentials
    ) -> StreamInfo:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{KICK_API}/livestreams",
                params={"broadcaster_user_id": channel_id},
                headers=self._headers(access_token),
            )
            r.raise_for_status()
            items = r.json().get("data", [])
            if not items:
                return StreamInfo(is_live=False)
            s = items[0]
            return StreamInfo(
                is_live=True,
                title=s.get("stream_title"),
                category_name=(s.get("category") or {}).get("name"),
                viewer_count=int(s.get("viewer_count", 0)),
            )

    async def check_token(self, access_token: str, creds: OAuthCredentials) -> PlatformStatus:
        try:
            await self._get_channel(access_token)
            return PlatformStatus(ok=True, message="Подключено")
        except httpx.HTTPError as e:
            return PlatformStatus(ok=False, message=f"Ошибка токена: {e}")
