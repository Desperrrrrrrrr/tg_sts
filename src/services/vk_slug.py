from __future__ import annotations

import re

_VK_URL = re.compile(r"(?:live\.vkvideo\.ru|vkplay\.live)/([^/?#\s]+)", re.I)


def parse_vk_channel_slug(text: str) -> str:
    text = text.strip()
    m = _VK_URL.search(text)
    if m:
        return m.group(1).lower()
    slug = text.lstrip("@/").split()[0].split("?")[0]
    return slug.lower()


def vk_needs_slug(conn) -> bool:
    if conn.platform != "vk":
        return False
    slug = (conn.external_channel_name or conn.external_channel_id or "").lstrip("@/")
    return not slug or slug.isdigit()
