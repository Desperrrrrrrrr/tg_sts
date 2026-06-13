from __future__ import annotations

import httpx

from src.config import get_settings
from src.db.models import Platform
from src.platforms.base import CategoryResult, PlatformAdapter, PlatformStatus, StreamInfo
from src.platforms.credentials import OAuthCredentials

TROVO_AUTH = "https://open-api.trovo.live/openplatform/exchangetoken"
TROVO_API = "https://open-api.trovo.live/openplatform"


class TrovoAdapter(PlatformAdapter):
    platform = Platform.TROVO

    def _headers(self, access_token: str, client_id: str) -> dict[str, str]:
        return {
            "Client-ID": client_id,
            "Authorization": f"OAuth {access_token}",
            "Accept": "application/json",
        }

    def get_oauth_url(self, state: str, creds: OAuthCredentials) -> str | None:
        if not creds.configured:
            return None
        redirect = f"{get_settings().oauth_callback_base}/trovo"
        scopes = "channel_details_self+channel_update_self"
        return (
            "https://open.trovo.live/page/login.html"
            f"?client_id={creds.client_id}"
            f"&response_type=code"
            f"&scope={scopes}"
            f"&redirect_uri={redirect}"
            f"&state={state}"
        )

    async def exchange_code(
        self,
        code: str,
        creds: OAuthCredentials,
        *,
        code_verifier: str | None = None,
        device_id: str | None = None,
        oauth_state: str | None = None,
    ) -> dict:
        redirect = f"{get_settings().oauth_callback_base}/trovo"
        async with httpx.AsyncClient() as client:
            r = await client.post(
                TROVO_AUTH,
                headers={"Accept": "application/json", "Client-ID": creds.client_id},
                json={
                    "client_secret": creds.client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect,
                },
            )
            r.raise_for_status()
            data = r.json()
            channel = await self._get_channel(data["access_token"], creds.client_id)
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in"),
                "channel_id": str(channel.get("channel_id", "")),
                "channel_name": channel.get("username", ""),
            }

    async def refresh_access_token(
        self, refresh_token: str, creds: OAuthCredentials, *, device_id: str | None = None
    ) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                TROVO_AUTH,
                headers={"Accept": "application/json", "Client-ID": creds.client_id},
                json={
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

    async def _get_channel(self, access_token: str, client_id: str) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{TROVO_API}/channels/id", headers=self._headers(access_token, client_id))
            r.raise_for_status()
            return r.json()

    async def search_categories(
        self, query: str, access_token: str, creds: OAuthCredentials
    ) -> list[CategoryResult]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{TROVO_API}/games",
                params={"query": query, "limit": 10},
                headers=self._headers(access_token, creds.client_id),
            )
            r.raise_for_status()
            items = r.json().get("category_info", r.json().get("games", []))
            return [
                CategoryResult(id=str(c.get("id", c.get("category_id", ""))), name=c.get("name", ""))
                for c in items
            ]

    async def update_stream(
        self,
        access_token: str,
        channel_id: str,
        creds: OAuthCredentials,
        *,
        title: str | None = None,
        category_id: str | None = None,
    ) -> None:
        body: dict = {"channel_id": int(channel_id)}
        if title is not None:
            body["live_title"] = title
        if category_id is not None:
            body["category_id"] = category_id
        if len(body) <= 1:
            return
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{TROVO_API}/channels/update",
                headers={**self._headers(access_token, creds.client_id), "Content-Type": "application/json"},
                json=body,
            )
            r.raise_for_status()

    async def get_stream_info(
        self, access_token: str, channel_id: str, creds: OAuthCredentials
    ) -> StreamInfo:
        channel = await self._get_channel(access_token, creds.client_id)
        if not channel.get("is_live"):
            return StreamInfo(is_live=False)
        return StreamInfo(
            is_live=True,
            title=channel.get("live_title"),
            category_name=channel.get("category_name"),
            viewer_count=int(channel.get("current_viewers", 0)),
        )

    async def check_token(self, access_token: str, creds: OAuthCredentials) -> PlatformStatus:
        try:
            await self._get_channel(access_token, creds.client_id)
            return PlatformStatus(ok=True, message="Подключено")
        except httpx.HTTPError as e:
            return PlatformStatus(ok=False, message=f"Ошибка токена: {e}")
