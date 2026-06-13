from __future__ import annotations

import httpx

from src.config import get_settings
from src.db.models import Platform
from src.platforms.base import CategoryResult, PlatformAdapter, PlatformStatus, StreamInfo
from src.platforms.credentials import OAuthCredentials

GOOGLE_AUTH = "https://oauth2.googleapis.com"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"


class YouTubeAdapter(PlatformAdapter):
    platform = Platform.YOUTUBE

    def get_oauth_url(self, state: str, creds: OAuthCredentials) -> str | None:
        if not creds.configured:
            return None
        redirect = f"{get_settings().oauth_callback_base}/youtube"
        scope = "https://www.googleapis.com/auth/youtube"
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={creds.client_id}"
            f"&redirect_uri={redirect}"
            f"&response_type=code"
            f"&scope={scope}"
            f"&access_type=offline"
            f"&prompt=consent"
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
        redirect = f"{get_settings().oauth_callback_base}/youtube"
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{GOOGLE_AUTH}/token",
                data={
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect,
                },
            )
            r.raise_for_status()
            data = r.json()
            channel = await self._get_channel(data["access_token"])
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in"),
                "channel_id": channel["id"],
                "channel_name": channel.get("snippet", {}).get("title", ""),
            }

    async def refresh_access_token(
        self, refresh_token: str, creds: OAuthCredentials, *, device_id: str | None = None
    ) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{GOOGLE_AUTH}/token",
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
                "refresh_token": refresh_token,
                "expires_in": data.get("expires_in"),
            }

    async def _get_channel(self, access_token: str) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{YOUTUBE_API}/channels",
                params={"part": "snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            r.raise_for_status()
            return r.json()["items"][0]

    async def search_categories(
        self, query: str, access_token: str, creds: OAuthCredentials
    ) -> list[CategoryResult]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{YOUTUBE_API}/videoCategories",
                params={"part": "snippet", "regionCode": "RU"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            r.raise_for_status()
            q = query.lower()
            return [
                CategoryResult(id=item["id"], name=item["snippet"]["title"])
                for item in r.json().get("items", [])
                if q in item["snippet"]["title"].lower() or "game" in q
            ][:10]

    async def _active_broadcast(self, access_token: str) -> dict | None:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{YOUTUBE_API}/liveBroadcasts",
                params={"part": "snippet,status", "broadcastStatus": "active", "mine": "true"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            r.raise_for_status()
            items = r.json().get("items", [])
            return items[0] if items else None

    async def update_stream(
        self,
        access_token: str,
        channel_id: str,
        creds: OAuthCredentials,
        *,
        title: str | None = None,
        category_id: str | None = None,
    ) -> None:
        broadcast = await self._active_broadcast(access_token)
        if not broadcast:
            raise ValueError("Нет активной трансляции на YouTube")
        snippet = broadcast["snippet"]
        if title is not None:
            snippet["title"] = title
        if category_id is not None:
            snippet["categoryId"] = category_id
        async with httpx.AsyncClient() as client:
            r = await client.put(
                f"{YOUTUBE_API}/liveBroadcasts",
                params={"part": "snippet"},
                headers={"Authorization": f"Bearer {access_token}"},
                json={"id": broadcast["id"], "snippet": snippet},
            )
            r.raise_for_status()

    async def get_stream_info(
        self, access_token: str, channel_id: str, creds: OAuthCredentials
    ) -> StreamInfo:
        broadcast = await self._active_broadcast(access_token)
        if not broadcast:
            return StreamInfo(is_live=False)
        return StreamInfo(
            is_live=True,
            title=broadcast["snippet"].get("title"),
            category_name=broadcast["snippet"].get("categoryId"),
        )

    async def check_token(self, access_token: str, creds: OAuthCredentials) -> PlatformStatus:
        try:
            await self._get_channel(access_token)
            return PlatformStatus(ok=True, message="Подключено")
        except httpx.HTTPError as e:
            return PlatformStatus(ok=False, message=f"Ошибка токена: {e}")
