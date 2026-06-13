from __future__ import annotations

import re

import httpx

from src.config import get_settings
from src.db.models import Platform
from src.platforms.base import CategoryResult, PlatformAdapter, PlatformStatus, StreamInfo
from src.platforms.credentials import OAuthCredentials
from src.platforms.category_utils import (
    clean_game_query,
    rank_categories,
    search_query_variants,
    twitch_exact_game_names,
    twitch_known_games,
)

TWITCH_AUTH = "https://id.twitch.tv/oauth2"
TWITCH_API = "https://api.twitch.tv/helix"


class TwitchAdapter(PlatformAdapter):
    platform = Platform.TWITCH

    def _headers(self, access_token: str, client_id: str) -> dict[str, str]:
        return {"Client-ID": client_id, "Authorization": f"Bearer {access_token}"}

    def get_oauth_url(self, state: str, creds: OAuthCredentials) -> str | None:
        if not creds.configured:
            return None
        redirect = f"{get_settings().oauth_callback_base}/twitch"
        scopes = "channel:manage:broadcast+user:read:email"
        return (
            f"{TWITCH_AUTH}/authorize"
            f"?client_id={creds.client_id}"
            f"&redirect_uri={redirect}"
            f"&response_type=code"
            f"&scope={scopes}"
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
        redirect = f"{get_settings().oauth_callback_base}/twitch"
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{TWITCH_AUTH}/token",
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
            user = await self._get_user(data["access_token"], creds.client_id)
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in"),
                "channel_id": user["id"],
                "channel_name": user["login"],
            }

    async def refresh_access_token(
        self, refresh_token: str, creds: OAuthCredentials, *, device_id: str | None = None
    ) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{TWITCH_AUTH}/token",
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

    async def _get_user(self, access_token: str, client_id: str) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{TWITCH_API}/users", headers=self._headers(access_token, client_id))
            r.raise_for_status()
            return r.json()["data"][0]

    async def search_categories(
        self, query: str, access_token: str, creds: OAuthCredentials
    ) -> list[CategoryResult]:
        query = clean_game_query(query)
        seen: set[str] = set()
        merged: list[CategoryResult] = []
        display_names: dict[str, str] = {}
        async with httpx.AsyncClient() as client:
            known = twitch_known_games(query)
            if known:
                r = await client.get(
                    f"{TWITCH_API}/games",
                    params=[("id", gid) for gid, _ in known],
                    headers=self._headers(access_token, creds.client_id),
                )
                r.raise_for_status()
                for item in r.json().get("data", []):
                    cid = item["id"]
                    label = next((d for gid, d in known if gid == cid), item["name"])
                    display_names[cid] = label
                    if cid not in seen:
                        seen.add(cid)
                        merged.append(CategoryResult(id=cid, name=label))
            exact_names = twitch_exact_game_names(query)
            if exact_names:
                r = await client.get(
                    f"{TWITCH_API}/games",
                    params=[("name", n) for n in exact_names[:20]],
                    headers=self._headers(access_token, creds.client_id),
                )
                r.raise_for_status()
                for item in r.json().get("data", []):
                    cid = item["id"]
                    name = display_names.get(cid, item["name"])
                    if cid not in seen:
                        seen.add(cid)
                        merged.append(CategoryResult(id=cid, name=name))
            for variant in search_query_variants(query):
                r = await client.get(
                    f"{TWITCH_API}/search/categories",
                    params={"query": variant, "first": 20},
                    headers=self._headers(access_token, creds.client_id),
                )
                r.raise_for_status()
                for item in r.json().get("data", []):
                    cid = item["id"]
                    if cid in seen:
                        continue
                    seen.add(cid)
                    merged.append(CategoryResult(id=cid, name=item["name"]))
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
        body: dict[str, str] = {}
        if title is not None:
            body["title"] = title
        if category_id is not None:
            body["game_id"] = category_id
        if not body:
            return
        async with httpx.AsyncClient() as client:
            r = await client.patch(
                f"{TWITCH_API}/channels",
                params={"broadcaster_id": channel_id},
                headers={**self._headers(access_token, creds.client_id), "Content-Type": "application/json"},
                json=body,
            )
            r.raise_for_status()

    async def get_channel_category(
        self, access_token: str, channel_id: str, creds: OAuthCredentials
    ) -> str | None:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{TWITCH_API}/channels",
                params={"broadcaster_id": channel_id},
                headers=self._headers(access_token, creds.client_id),
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            if not data:
                return None
            return data[0].get("game_name")

    async def get_channel_title(
        self, access_token: str, channel_id: str, creds: OAuthCredentials
    ) -> str | None:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{TWITCH_API}/channels",
                params={"broadcaster_id": channel_id},
                headers=self._headers(access_token, creds.client_id),
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            if not data:
                return None
            return data[0].get("title")

    async def get_stream_info(
        self, access_token: str, channel_id: str, creds: OAuthCredentials
    ) -> StreamInfo:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{TWITCH_API}/streams",
                params={"user_id": channel_id},
                headers=self._headers(access_token, creds.client_id),
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            if not data:
                return StreamInfo(is_live=False)
            s = data[0]
            return StreamInfo(
                is_live=True,
                title=s.get("title"),
                category_name=s.get("game_name"),
                viewer_count=int(s.get("viewer_count", 0)),
            )

    async def check_token(self, access_token: str, creds: OAuthCredentials) -> PlatformStatus:
        try:
            await self._get_user(access_token, creds.client_id)
            return PlatformStatus(ok=True, message="Подключено")
        except httpx.HTTPError as e:
            return PlatformStatus(ok=False, message=f"Ошибка токена: {e}")
