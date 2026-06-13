from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.platforms.base import CategoryResult

_WORD = re.compile(r"[a-z0-9]+")

_QUERY_ALIASES: dict[str, list[str]] = {
    "cs2": ["counter-strike 2", "counter strike 2", "Counter-Strike 2"],
    "cs 2": ["counter-strike 2", "counter strike 2", "Counter-Strike 2"],
    "csgo": ["counter-strike global offensive", "counter strike", "Counter-Strike: Global Offensive"],
    "dota": ["dota 2", "Dota 2"],
}

# Известные игры: Helix /games?name=Counter-Strike 2 пустой, но id=32399 — это CS2 на Twitch.
_TWITCH_KNOWN_GAMES: dict[str, tuple[str, str]] = {
    "cs2": ("32399", "Counter-Strike 2"),
    "cs 2": ("32399", "Counter-Strike 2"),
    "counterstrike2": ("32399", "Counter-Strike 2"),
    "counterstrike 2": ("32399", "Counter-Strike 2"),
    "counter strike 2": ("32399", "Counter-Strike 2"),
    "counter-strike 2": ("32399", "Counter-Strike 2"),
    "counter-strike-2": ("32399", "Counter-Strike 2"),
    "counterstrike": ("32399", "Counter-Strike 2"),
}

# Точные имена для GET /helix/games?name= (exact match; CS2 там — «Counter-Strike»).
_TWITCH_EXACT_GAME_NAMES: dict[str, str] = {
    "cs2": "Counter-Strike",
    "cs 2": "Counter-Strike",
    "counterstrike2": "Counter-Strike",
    "counterstrike 2": "Counter-Strike",
    "counter strike 2": "Counter-Strike",
    "counter-strike 2": "Counter-Strike",
    "counter-strike-2": "Counter-Strike",
    "csgo": "Counter-Strike: Global Offensive",
    "counterstrikeglobaloffensive": "Counter-Strike: Global Offensive",
}


def clean_game_query(query: str) -> str:
    q = query.strip()
    if len(q) >= 2 and q[0] == q[-1] and q[0] in "\"'«»":
        q = q[1:-1].strip()
    return q


def known_display_names(query: str) -> set[str]:
    """Нормализованные канонические названия для запроса (все площадки)."""
    q = clean_game_query(query)
    names: set[str] = set()
    hit = _TWITCH_KNOWN_GAMES.get(normalize_category_name(q))
    if hit:
        names.add(normalize_category_name(hit[1]))
    for alias in _QUERY_ALIASES.get(q.lower(), []):
        names.add(normalize_category_name(alias))
    return names


def twitch_known_games(query: str) -> list[tuple[str, str]]:
    """(game_id, display_name) для запросов, где search/categories ошибается."""
    key = normalize_category_name(clean_game_query(query))
    hit = _TWITCH_KNOWN_GAMES.get(key)
    return [hit] if hit else []


def twitch_exact_game_names(query: str) -> list[str]:
    """Имена для GET /helix/games?name= (точное совпадение, не fuzzy search)."""
    q = clean_game_query(query)
    key = normalize_category_name(q)
    names: list[str] = []
    exact = _TWITCH_EXACT_GAME_NAMES.get(key)
    if exact:
        names.append(exact)
    for alias in _QUERY_ALIASES.get(q.lower(), []):
        if alias[0].isupper() and alias not in names:
            names.append(alias)
    if q and q not in names:
        names.append(q)
    title = q.title().replace(" ", "-") if " " in q else q
    if "counter" in q.lower() and "strike" in q.lower() and "2" in q:
        if "Counter-Strike" not in names:
            names.append("Counter-Strike")
    return names


def normalize_category_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def search_query_variants(query: str) -> list[str]:
    """Варианты запроса для /search/categories."""
    q = clean_game_query(query)
    if not q:
        return []
    variants = [q]
    spaced = re.sub(r"[-_]+", " ", q)
    hyphen = re.sub(r"\s+", "-", q.strip())
    compact = re.sub(r"[\s\-_]+", "", q)
    for v in (spaced, hyphen, compact):
        if v and v.lower() not in {x.lower() for x in variants}:
            variants.append(v)
    m = re.match(r"^(.*?)[\s\-_]+(\d+)$", q)
    if m:
        base = m.group(1).strip()
        for v in (base, base.replace(" ", "-"), base.replace("-", " ")):
            if v and v.lower() not in {x.lower() for x in variants}:
                variants.append(v)
    for alias in _QUERY_ALIASES.get(q.lower(), []):
        if alias.lower() not in {x.lower() for x in variants}:
            variants.append(alias)
    return variants


def match_score(query: str, name: str) -> float:
    nq = normalize_category_name(query)
    nn = normalize_category_name(name)
    if not nq or not nn:
        return 0.0
    if nq == nn:
        return 1.0
    if nn.startswith(nq):
        if len(nn) == len(nq):
            return 0.96
        # cs2 не должно матчиться на cs2d по общему префиксу
        if nn[len(nq) : len(nq) + 1].isalnum():
            pass
        elif len(nq) <= 4:
            return 0.55
        else:
            return 0.85
    q_tokens = _WORD.findall(clean_game_query(query).lower())
    n_tokens = _WORD.findall(name.lower())
    n_token_set = set(n_tokens)
    if q_tokens and all(t in n_token_set for t in q_tokens):
        extra = len(n_tokens) - len(q_tokens)
        if extra == 0:
            return 0.98 if nq != nn else 1.0
        # «counter strike 2» не должно побеждать «Counter-Strike Online 2»
        return max(0.35, 0.92 - extra * 0.22)
    if nq in nn and nq != nn:
        idx = nn.find(nq)
        before_ok = idx == 0 or not nn[idx - 1].isalnum()
        after_idx = idx + len(nq)
        after_ok = after_idx == len(nn) or not nn[after_idx].isalnum()
        if before_ok and after_ok:
            return 0.82
    overlap = sum(1 for t in q_tokens if t in n_tokens)
    if q_tokens and overlap == len(q_tokens):
        return 0.9
    if overlap >= max(1, len(q_tokens) - 1):
        return 0.75
    return 0.4 if overlap else 0.0


def rank_categories(query: str, results: list[CategoryResult]) -> list[CategoryResult]:
    from src.platforms.base import CategoryResult as CR

    if not results:
        return []
    known_ids = {gid for gid, _ in twitch_known_games(query)}
    preferred = known_display_names(query)
    scored: list[tuple[CategoryResult, float]] = []
    for r in results:
        if r.id in known_ids or normalize_category_name(r.name) in preferred:
            score = 1.0
        else:
            score = match_score(query, r.name)
        scored.append((r, score))
    scored.sort(key=lambda x: (-x[1], x[0].name.lower()))
    return [CR(r.id, r.name, confidence=score) for r, score in scored]
