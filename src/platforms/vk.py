from __future__ import annotations

import base64
import json
import logging
from urllib.parse import urlencode

import httpx

from src.config import get_settings
from src.db.models import Platform
from src.platforms.base import CategoryResult, PlatformAdapter, PlatformStatus, StreamInfo
from src.platforms.credentials import OAuthCredentials
from src.platforms.category_utils import rank_categories, search_query_variants

logger = logging.getLogger(__name__)

VK_OAUTH_AUTH = "https://live.vkvideo.ru/app/oauth2/authorize"
VK_OAUTH_TOKEN = "https://api.live.vkvideo.ru/oauth/server/token"
VK_OAUTH_WEB_REFRESH = "https://api.live.vkvideo.ru/oauth/token/"
VK_API = "https://api.live.vkvideo.ru/v1"
VK_DEVAPI = "https://api.live.vkvideo.ru"

# Scopes из play-code-live/vkplay-live-sdk (Scope.php). Запись стрима там не описана.
VK_OAUTH_SCOPES = (
    "channel:credentials,"
    "channel:roles,"
    "channel:points,"
    "channel:points:rewards,"
    "channel:points:rewards:demands,"
    "chat:settings,"
    "chat:message:send"
)

_BROWSER_HEADERS = {
    "Origin": "https://live.vkvideo.ru",
    "Referer": "https://live.vkvideo.ru/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
}


class VKApiUnavailableError(RuntimeError):
    """VK Video Live API недоступен или отклонил запрос."""


def _basic_auth(creds: OAuthCredentials) -> str:
    raw = f"{creds.client_id}:{creds.client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _auth_headers(access_token: str | None, creds: OAuthCredentials) -> dict[str, str]:
    if access_token:
        headers = {"Authorization": f"Bearer {access_token}"}
    else:
        headers = {"Authorization": _basic_auth(creds)}
    headers["Accept"] = "application/json"
    headers.update(_BROWSER_HEADERS)
    if creds.client_id:
        headers["X-From-Id"] = creds.client_id
        headers["From-Client-Id"] = creds.client_id
    return headers


def _jwt_claims(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _slug_from_token_payload(data: dict, access_token: str) -> tuple[str, str]:
    """Из ответа OAuth / JWT — user_id и slug канала."""
    user_id = str(
        data.get("user_id")
        or data.get("owner_id")
        or data.get("uid")
        or data.get("sub")
        or ""
    )
    slug = str(
        data.get("blog_url")
        or data.get("blogUrl")
        or data.get("channel")
        or data.get("channel_slug")
        or data.get("nick")
        or data.get("login")
        or data.get("username")
        or ""
    ).lstrip("@/")
    if not slug:
        claims = _jwt_claims(access_token)
        user_id = user_id or str(claims.get("sub", claims.get("user_id", "")))
        slug = str(
            claims.get("blog_url")
            or claims.get("blogUrl")
            or claims.get("nick")
            or claims.get("login")
            or claims.get("channel")
            or ""
        ).lstrip("@/")
    return user_id, slug


def _parse_categories(payload: dict) -> list[CategoryResult]:
    data = payload.get("data", payload)
    if isinstance(data, dict):
        items = data.get("categories", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [
        CategoryResult(id=str(c["id"]), name=c.get("title", c.get("name", "")))
        for c in items
        if c.get("id")
    ]


def _serialize_title(title: str) -> str:
    blocks = [
        {
            "type": "text",
            "content": json.dumps([title, "unstyled", []], ensure_ascii=False),
            "modificator": "",
        }
    ]
    return json.dumps(blocks, ensure_ascii=False)


def _parse_stream_title(stream: dict) -> str | None:
    plain = stream.get("title")
    if isinstance(plain, str) and plain.strip():
        return plain.strip()
    for key in ("titleData", "title_data"):
        raw = stream.get(key)
        if not raw:
            continue
        try:
            blocks = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            continue
        if not isinstance(blocks, list):
            continue
        parts: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            content = block.get("content")
            if not content:
                continue
            try:
                parsed = json.loads(content)
                if isinstance(parsed, list) and parsed:
                    parts.append(str(parsed[0]))
            except (json.JSONDecodeError, TypeError):
                parts.append(str(content))
        text = "".join(parts).strip()
        if text:
            return text
    return None


def _extract_slug(payload: dict) -> tuple[str, str]:
    data = payload.get("data", payload)
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
        data = data["data"]
    user_id = ""
    slug = ""
    if isinstance(data, dict):
        user_id = str(data.get("id", data.get("user_id", "")))
        slug = (
            data.get("blogUrl")
            or data.get("nick")
            or data.get("name")
            or (data.get("owner") or {}).get("nick")
            or (data.get("owner") or {}).get("name")
            or (data.get("blog") or {}).get("blogUrl")
            or ""
        )
    return user_id, str(slug).lstrip("@/")


def _looks_like_slug(value: str) -> bool:
    value = value.lstrip("@/")
    return bool(value) and not value.isdigit()


class VKAdapter(PlatformAdapter):
    platform = Platform.VK

    def get_oauth_url(self, state: str, creds: OAuthCredentials) -> str | None:
        if not creds.configured:
            return None
        redirect = f"{get_settings().oauth_callback_base}/vk"
        params = urlencode(
            {
                "response_type": "code",
                "client_id": creds.client_id,
                "redirect_uri": redirect,
                "state": state,
                "scope": VK_OAUTH_SCOPES,
            }
        )
        return f"{VK_OAUTH_AUTH}?{params}"

    async def exchange_code(
        self,
        code: str,
        creds: OAuthCredentials,
        *,
        code_verifier: str | None = None,
        device_id: str | None = None,
        oauth_state: str | None = None,
    ) -> dict:
        redirect = f"{get_settings().oauth_callback_base}/vk"
        async with httpx.AsyncClient() as client:
            r = await client.post(
                VK_OAUTH_TOKEN,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect,
                },
                headers={
                    "Authorization": _basic_auth(creds),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            r.raise_for_status()
            data = r.json()
            access_token = data["access_token"]
            user_id, channel_name = _slug_from_token_payload(data, access_token)
            if not channel_name:
                user_id, channel_name = await self._fetch_slug(client, access_token, creds)
            return {
                "access_token": access_token,
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in"),
                "channel_id": channel_name or user_id,
                "channel_name": channel_name,
            }

    async def refresh_access_token(
        self,
        refresh_token: str,
        creds: OAuthCredentials,
        *,
        device_id: str | None = None,
    ) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                VK_OAUTH_TOKEN,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={
                    "Authorization": _basic_auth(creds),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            r.raise_for_status()
            data = r.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", refresh_token),
                "expires_in": data.get("expires_in"),
            }

    async def _fetch_slug(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        creds: OAuthCredentials,
    ) -> tuple[str, str]:
        for path in ("/user/current", "/user/me"):
            try:
                r = await client.get(
                    f"{VK_API}{path}",
                    headers=_auth_headers(access_token, creds),
                )
                if r.status_code == 200:
                    return _extract_slug(r.json())
            except httpx.HTTPError:
                pass
        return "", ""

    async def _api_get(
        self,
        client: httpx.AsyncClient,
        path: str,
        access_token: str,
        creds: OAuthCredentials,
        *,
        params: dict | None = None,
    ) -> httpx.Response:
        headers = _auth_headers(access_token, creds)
        return await client.get(f"{VK_API}{path}", params=params, headers=headers)

    async def _resolve_channel_slug(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        creds: OAuthCredentials,
        channel_id: str,
    ) -> str:
        slug = channel_id.lstrip("@/") if channel_id else ""
        if _looks_like_slug(slug):
            return slug
        _, resolved = await self._fetch_slug(client, access_token, creds)
        if resolved:
            return resolved
        raise VKApiUnavailableError(
            "Не указан slug канала VK. Открой ⚙️ → VK → «🔗 Подключить» "
            "и после OAuth отправь slug (из URL live.vkvideo.ru/твой_ник)."
        )

    async def _search_categories_once(
        self,
        client: httpx.AsyncClient,
        query: str,
        access_token: str,
        creds: OAuthCredentials,
    ) -> list[CategoryResult]:
        params = {"search": query, "limit": 10, "type": "game"}
        r = await self._api_get(
            client,
            "/public_video_stream/category/",
            access_token,
            creds,
            params=params,
        )
        if r.status_code == 404:
            raise VKApiUnavailableError("VK category search недоступен (404)")
        if r.status_code in (401, 403):
            raise VKApiUnavailableError(f"VK API auth: {r.status_code}")
        r.raise_for_status()
        return _parse_categories(r.json())

    async def search_categories(
        self, query: str, access_token: str, creds: OAuthCredentials
    ) -> list[CategoryResult]:
        async with httpx.AsyncClient() as client:
            seen: set[str] = set()
            merged: list[CategoryResult] = []
            for variant in search_query_variants(query):
                for cat in await self._search_categories_once(
                    client, variant, access_token, creds
                ):
                    if cat.id not in seen:
                        seen.add(cat.id)
                        merged.append(cat)
            return rank_categories(query, merged)[:10]

    async def _fetch_current_title(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        creds: OAuthCredentials,
        slug: str,
    ) -> str | None:
        r = await self._api_get(client, f"/blog/{slug}", access_token, creds)
        if r.status_code != 200:
            return None
        data = r.json().get("data", r.json())
        stream = data.get("stream") or data.get("publicVideoStream") or data
        if isinstance(stream, dict):
            return _parse_stream_title(stream)
        return None

    async def update_stream(
        self,
        access_token: str,
        channel_id: str,
        creds: OAuthCredentials,
        *,
        title: str | None = None,
        category_id: str | None = None,
        web_access_token: str | None = None,
    ) -> None:
        if title is None and category_id is None:
            return
        write_token = web_access_token or access_token
        async with httpx.AsyncClient() as client:
            slug = await self._resolve_channel_slug(client, access_token, creds, channel_id)
            send_title = title
            # VK manage/stream сбрасывает title, если передать только category_id.
            if category_id is not None and title is None:
                current = await self._fetch_current_title(client, access_token, creds, slug)
                if current:
                    send_title = current
            if await self._try_web_manage_stream(
                client, write_token, creds, slug, title=send_title, category_id=category_id
            ):
                return
            ok_cat = not category_id
            ok_title = title is None
            if category_id:
                ok_cat = await self._try_devapi_set_category(client, write_token, creds, category_id)
            if title:
                ok_title = await self._try_devapi_set_info(client, write_token, creds, title)
            if ok_cat and ok_title:
                return
            raise VKApiUnavailableError(
                "DevAPI-токен не даёт запись на VK. Добавь session-токен: "
                "⚙️ → VK Video Live → «🔑 Session-токен VK» (auth из localStorage браузера)."
            )

    async def _try_web_manage_stream(
        self,
        client: httpx.AsyncClient,
        token: str,
        creds: OAuthCredentials,
        slug: str,
        *,
        title: str | None,
        category_id: str | None,
    ) -> bool:
        headers = _auth_headers(token, creds)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        form: dict[str, str] = {}
        if title is not None:
            form["title_data"] = _serialize_title(title)
        if category_id is not None:
            form["category_id"] = category_id
        if not form:
            return True
        r = await client.put(
            f"{VK_API}/channel/{slug}/manage/stream",
            headers=headers,
            data=form,
        )
        if r.status_code in (200, 204):
            return True
        if r.status_code == 404:
            return False
        logger.warning("VK manage/stream %s: %s", r.status_code, r.text[:200])
        return False

    async def _try_devapi_set_category(
        self,
        client: httpx.AsyncClient,
        token: str,
        creds: OAuthCredentials,
        category_id: str,
    ) -> bool:
        headers = _auth_headers(token, creds)
        headers["Content-Type"] = "application/json"
        for base in (VK_DEVAPI, "https://api.vkplay.live"):
            for path in ("/v1/stream/set_category", "/v1/channel/stream/category"):
                r = await client.post(
                    f"{base}{path}",
                    headers=headers,
                    json={"category_id": category_id},
                )
                if r.status_code in (200, 204):
                    return True
                if r.status_code not in (401, 403, 404):
                    logger.warning("VK DevAPI %s%s -> %s", base, path, r.status_code)
        return False

    async def _try_devapi_set_info(
        self,
        client: httpx.AsyncClient,
        token: str,
        creds: OAuthCredentials,
        title: str,
    ) -> bool:
        headers = _auth_headers(token, creds)
        headers["Content-Type"] = "application/json"
        for base in (VK_DEVAPI, "https://api.vkplay.live"):
            r = await client.post(
                f"{base}/v1/stream/set_info",
                headers=headers,
                json={"title": title},
            )
            if r.status_code in (200, 204):
                return True
        return False

    async def get_stream_info(
        self, access_token: str, channel_id: str, creds: OAuthCredentials
    ) -> StreamInfo:
        async with httpx.AsyncClient() as client:
            slug = await self._resolve_channel_slug(client, access_token, creds, channel_id)
            r = await self._api_get(client, f"/blog/{slug}", access_token, creds)
            if r.status_code == 404:
                return StreamInfo(is_live=False)
            r.raise_for_status()
            payload = r.json()
            data = payload.get("data", payload)
            stream = data.get("stream") or data.get("publicVideoStream") or data
            if not isinstance(stream, dict):
                return StreamInfo(is_live=False)
            is_live = bool(stream.get("isOnline", stream.get("online", stream.get("is_live"))))
            category = stream.get("category") or {}
            return StreamInfo(
                is_live=is_live,
                title=_parse_stream_title(stream) or stream.get("title"),
                category_name=category.get("title") or category.get("name"),
                viewer_count=int((stream.get("count") or {}).get("viewers", 0)),
            )

    async def check_token(self, access_token: str, creds: OAuthCredentials) -> PlatformStatus:
        try:
            async with httpx.AsyncClient() as client:
                _, slug = await self._fetch_slug(client, access_token, creds)
                if slug:
                    return PlatformStatus(ok=True, message=f"Подключено (@{slug})")
                r = await self._api_get(
                    client,
                    "/public_video_stream/category/",
                    access_token,
                    creds,
                    params={"search": "game", "limit": 1},
                )
                if r.status_code == 200:
                    return PlatformStatus(
                        ok=True,
                        message="OAuth OK. Укажи slug канала (live.vkvideo.ru/ник) для смены игры.",
                    )
                if r.status_code in (401, 403):
                    return PlatformStatus(ok=False, message=f"Токен отклонён ({r.status_code})")
                r.raise_for_status()
            return PlatformStatus(ok=True, message="Подключено")
        except httpx.HTTPError as e:
            return PlatformStatus(ok=False, message=f"Ошибка токена: {e}")
