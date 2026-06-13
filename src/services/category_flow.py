from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import GameMapping, Platform, PlatformConnection
from src.platforms.base import GENERIC_CATEGORIES, CategoryResult
from src.platforms.registry import get_adapter
from src.platforms.vk import VKApiUnavailableError
from src.services.platform_creds import get_credentials
from src.services.token_manager import get_access_token

logger = logging.getLogger(__name__)


@dataclass
class CategoryPickState:
    game_query: str
    title: str | None = None
    pending: dict[str, CategoryResult | None] = field(default_factory=dict)
    choices: dict[str, list[CategoryResult]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


async def resolve_categories(
    session: AsyncSession,
    user_id: int,
    connections: list[PlatformConnection],
    game_query: str,
    platform_filter: Platform | None = None,
) -> CategoryPickState:
    state = CategoryPickState(game_query=game_query)
    for conn in connections:
        if not conn.enabled:
            continue
        platform = Platform(conn.platform)
        if platform_filter and platform != platform_filter:
            continue
        cached = await _get_cached(session, user_id, game_query, platform)
        if cached:
            state.pending[platform.value] = cached
            continue
        creds = await get_credentials(session, conn)
        token = await get_access_token(session, conn)
        if not creds or not token:
            state.pending[platform.value] = None
            state.choices[platform.value] = []
            continue
        adapter = get_adapter(platform)
        try:
            best = await adapter.find_best_category(game_query, token, creds)
            if best and best.confidence >= 1.0:
                state.pending[platform.value] = best
            else:
                all_results = await adapter.search_categories(game_query, token, creds)
                state.choices[platform.value] = all_results[:5] if all_results else []
                state.pending[platform.value] = None
        except VKApiUnavailableError:
            state.errors[platform.value] = (
                "поиск игр через DevAPI недоступен (404 на api.live.vkvideo.ru). "
                "OAuth в порядке — выбери категорию вручную."
            )
            state.pending[platform.value] = None
            state.choices[platform.value] = []
        except Exception as e:
            logger.exception("Category search failed for %s", platform.value)
            state.errors[platform.value] = str(e)
            state.pending[platform.value] = None
            state.choices[platform.value] = []
    return state


async def _get_cached(
    session: AsyncSession, user_id: int, game_query: str, platform: Platform
) -> CategoryResult | None:
    r = await session.execute(
        select(GameMapping).where(
            GameMapping.user_id == user_id,
            GameMapping.game_query == game_query.lower(),
            GameMapping.platform == platform.value,
        )
    )
    row = r.scalar_one_or_none()
    if row:
        return CategoryResult(id=row.category_id, name=row.category_name)
    return None


async def cache_mapping(
    session: AsyncSession, user_id: int, game_query: str, platform: Platform, category: CategoryResult
) -> None:
    r = await session.execute(
        select(GameMapping).where(
            GameMapping.user_id == user_id,
            GameMapping.game_query == game_query.lower(),
            GameMapping.platform == platform.value,
        )
    )
    row = r.scalar_one_or_none()
    if row:
        row.category_id = category.id
        row.category_name = category.name
    else:
        session.add(
            GameMapping(
                user_id=user_id,
                game_query=game_query.lower(),
                platform=platform.value,
                category_id=category.id,
                category_name=category.name,
            )
        )
    await session.commit()


def generic_for_platform(platform: Platform) -> list[CategoryResult]:
    return GENERIC_CATEGORIES.get(platform, [CategoryResult("other", "Other")])
