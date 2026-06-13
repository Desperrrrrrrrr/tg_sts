from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from src.bot.platform_status import PlatformLinkStatus, platform_button_label
from src.db.models import PLATFORM_LABELS, Platform

BTN_GAME_ALL = "🎮 Игра — везде"
BTN_TITLE_ALL = "✏️ Название — везде"
BTN_STATUS = "📊 Статус"
BTN_SETTINGS = "⚙️ Настройки"
BTN_PLATFORMS = "📡 Площадки"
BTN_ADD_PLATFORM = "➕ Добавить площадку"
BTN_ANNOUNCE = "📢 Канал анонсов"
BTN_BACK = "« Назад"
BTN_GAME = "🎮 Сменить игру"
BTN_TITLE = "✏️ Сменить название"
BTN_CONNECT = "🔗 Подключить аккаунт"
BTN_KEYS = "🔑 Ключи приложения"
BTN_DISCONNECT = "🔌 Отключить"
BTN_VK_SESSION = "🔑 Session-токен VK"

ALL_MENU_BUTTONS = frozenset({
    BTN_GAME_ALL,
    BTN_TITLE_ALL,
    BTN_STATUS,
    BTN_SETTINGS,
    BTN_PLATFORMS,
    BTN_ADD_PLATFORM,
    BTN_ANNOUNCE,
    BTN_BACK,
    BTN_GAME,
    BTN_TITLE,
    BTN_CONNECT,
    BTN_KEYS,
    BTN_DISCONNECT,
    BTN_VK_SESSION,
})


def is_menu_button(text: str | None) -> bool:
    if not text:
        return False
    if text in ALL_MENU_BUTTONS:
        return True
    from src.bot.platform_status import parse_platform_button

    return parse_platform_button(text) is not None


def label_to_platform(text: str) -> Platform | None:
    from src.bot.platform_status import parse_platform_button

    return parse_platform_button(text)


def persistent_keyboard() -> ReplyKeyboardMarkup:
    """Всегда под рукой: площадки, статус, настройки."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_PLATFORMS), KeyboardButton(text=BTN_STATUS)],
            [KeyboardButton(text=BTN_SETTINGS)],
        ],
        resize_keyboard=True,
    )


def main_keyboard(statuses: dict[str, PlatformLinkStatus]) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text=BTN_GAME_ALL), KeyboardButton(text=BTN_TITLE_ALL)],
    ]
    connected = [
        p for p in Platform if statuses.get(p.value, PlatformLinkStatus(False, False)).connected
    ]
    if connected:
        row: list[KeyboardButton] = []
        for p in connected:
            status = statuses.get(p.value, PlatformLinkStatus(False, False))
            row.append(KeyboardButton(text=platform_button_label(p, status)))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
    rows.append([KeyboardButton(text=BTN_PLATFORMS), KeyboardButton(text=BTN_STATUS)])
    rows.append([KeyboardButton(text=BTN_SETTINGS)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def settings_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADD_PLATFORM)],
            [KeyboardButton(text=BTN_ANNOUNCE)],
            [KeyboardButton(text=BTN_BACK)],
        ],
        resize_keyboard=True,
    )


def platforms_manage_keyboard(statuses: dict[str, PlatformLinkStatus]) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    row: list[KeyboardButton] = []
    for p in Platform:
        status = statuses.get(p.value, PlatformLinkStatus(False, False))
        row.append(KeyboardButton(text=platform_button_label(p, status)))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([KeyboardButton(text=BTN_ADD_PLATFORM)])
    rows.append([KeyboardButton(text=BTN_BACK)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def platform_keyboard(
    status: PlatformLinkStatus | None = None,
    platform: Platform | None = None,
) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = [[KeyboardButton(text=BTN_CONNECT)]]
    if platform == Platform.VK and status and status.connected:
        rows.append([KeyboardButton(text=BTN_VK_SESSION)])
    if status and (status.connected or status.has_keys):
        rows.append([KeyboardButton(text=BTN_DISCONNECT)])
    rows.append([KeyboardButton(text=BTN_GAME), KeyboardButton(text=BTN_TITLE)])
    rows.append([KeyboardButton(text=BTN_BACK)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
