from src.db.models import Platform
from src.platforms.base import PlatformAdapter
from src.platforms.kick import KickAdapter
from src.platforms.trovo import TrovoAdapter
from src.platforms.twitch import TwitchAdapter
from src.platforms.vk import VKAdapter
from src.platforms.youtube import YouTubeAdapter

_ADAPTERS: dict[Platform, PlatformAdapter] = {
    Platform.TWITCH: TwitchAdapter(),
    Platform.KICK: KickAdapter(),
    Platform.YOUTUBE: YouTubeAdapter(),
    Platform.VK: VKAdapter(),
    Platform.TROVO: TrovoAdapter(),
}


def get_adapter(platform: Platform) -> PlatformAdapter:
    return _ADAPTERS[platform]


def all_adapters() -> list[PlatformAdapter]:
    return list(_ADAPTERS.values())
