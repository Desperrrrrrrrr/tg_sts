from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.db.models import Platform
from src.platforms.category_utils import match_score
from src.platforms.credentials import OAuthCredentials


@dataclass
class CategoryResult:
    id: str
    name: str
    confidence: float = 1.0


@dataclass
class StreamInfo:
    is_live: bool
    title: str | None = None
    category_name: str | None = None
    viewer_count: int = 0


@dataclass
class PlatformStatus:
    ok: bool
    message: str


GENERIC_CATEGORIES: dict[Platform, list[CategoryResult]] = {
    Platform.TWITCH: [
        CategoryResult("509658", "Just Chatting"),
        CategoryResult("509672", "IRL"),
        CategoryResult("26936", "Music"),
    ],
    Platform.KICK: [
        CategoryResult("15", "Just Chatting"),
        CategoryResult("8549", "IRL"),
    ],
    Platform.YOUTUBE: [
        CategoryResult("20", "Gaming"),
        CategoryResult("22", "People & Blogs"),
    ],
    Platform.VK: [
        CategoryResult("just_chatting", "Just Chatting"),
        CategoryResult("irl", "IRL"),
        CategoryResult("other", "Other"),
    ],
    Platform.TROVO: [
        CategoryResult("10023", "Just Chatting"),
    ],
}


class PlatformAdapter(ABC):
    platform: Platform

    @abstractmethod
    def get_oauth_url(self, state: str, creds: OAuthCredentials) -> str | None:
        ...

    @abstractmethod
    async def exchange_code(
        self,
        code: str,
        creds: OAuthCredentials,
        *,
        code_verifier: str | None = None,
        device_id: str | None = None,
        oauth_state: str | None = None,
    ) -> dict:
        ...

    @abstractmethod
    async def refresh_access_token(
        self, refresh_token: str, creds: OAuthCredentials, *, device_id: str | None = None
    ) -> dict:
        ...

    @abstractmethod
    async def search_categories(
        self, query: str, access_token: str, creds: OAuthCredentials
    ) -> list[CategoryResult]:
        ...

    @abstractmethod
    async def update_stream(
        self,
        access_token: str,
        channel_id: str,
        creds: OAuthCredentials,
        *,
        title: str | None = None,
        category_id: str | None = None,
    ) -> None:
        ...

    @abstractmethod
    async def get_stream_info(
        self, access_token: str, channel_id: str, creds: OAuthCredentials
    ) -> StreamInfo:
        ...

    @abstractmethod
    async def check_token(self, access_token: str, creds: OAuthCredentials) -> PlatformStatus:
        ...

    async def find_best_category(
        self, query: str, access_token: str, creds: OAuthCredentials
    ) -> CategoryResult | None:
        results = await self.search_categories(query, access_token, creds)
        if not results:
            return None
        if results[0].confidence >= 0.9:
            return results[0]
        scored = [(r, match_score(query, r.name)) for r in results]
        scored.sort(key=lambda x: (-x[1], x[0].name.lower()))
        best, score = scored[0]
        return CategoryResult(best.id, best.name, confidence=score)
