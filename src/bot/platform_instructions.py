from src.db.models import PLATFORM_LABELS, Platform
from src.config import get_settings
from src.services.public_url import redirect_url_for


def server_requirement_note() -> str:
    return (
        "<b>🖥 Сервер (настраивает тот, кто поднял бота):</b>\n"
        "Нужен VPS/сервер со <b>статическим IP</b> и <b>доменом</b> "
        "(например <code>stream.mysite.ru</code>).\n"
        "Twitch и другие площадки принимают Redirect URL только по "
        "<code>https://</code> (кроме <code>localhost</code> для теста).\n"
        "Схема: интернет → nginx :443 (SSL) → бот :8080.\n\n"
        "<b>Redirect URL</b> — домен <i>этого</i> бота + путь площадки:\n"
        "<code>/oauth/twitch</code> · <code>/oauth/kick</code> · "
        "<code>/oauth/youtube</code> · <code>/oauth/vk</code> · <code>/oauth/trovo</code>\n"
    )


def redirect_block(platform: Platform) -> str:
    url = redirect_url_for(platform)
    label = PLATFORM_LABELS[platform]
    plat_slug = platform.value
    redirect_hint = (
        "В Twitch нажми «Добавить» после ввода.\n"
        if platform == Platform.TWITCH
        else ""
    )
    return (
        f"\n\n<b>📋 OAuth Redirect URL</b> для {label}:\n\n"
        f"Шаблон (свой домен при своём деплое):\n"
        f"<code>https://ТВОЙ-ДОМЕН/oauth/{plat_slug}</code>\n\n"
        f"Для <b>этого бота</b> вставь в кабинет площадки:\n"
        f"<code>{url}</code>\n\n"
        "⚠️ Вставь <b>именно строку «Для этого бота»</b>, без пробелов.\n"
        f"{redirect_hint}"
        "Должно совпадать с <code>PUBLIC_BASE_URL</code> на сервере бота "
        "(http/https, домен, путь <code>/oauth/...</code>)."
    )


def client_id_prompt(platform: Platform) -> str:
    label = PLATFORM_LABELS[platform]
    hints = {
        Platform.VK: (
            f"Отправь <b>ID приложения</b> из VK Video Live "
            f"(в боте это Client ID для {label}):"
        ),
        Platform.TWITCH: f"Отправь <b>Client ID</b> для {label}:",
        Platform.KICK: f"Отправь <b>Client ID</b> для {label}:",
        Platform.YOUTUBE: f"Отправь <b>Client ID</b> для {label}:",
        Platform.TROVO: f"Отправь <b>Client ID</b> для {label}:",
    }
    return hints.get(platform, f"Отправь <b>Client ID</b> для {label}:")


def client_secret_prompt(platform: Platform) -> str:
    label = PLATFORM_LABELS[platform]
    hints = {
        Platform.VK: (
            f"Отправь <b>Секретный ключ приложения</b> из VK Video Live "
            f"(в боте это Client Secret для {label}):\n\n"
            "❌ <b>Публичный ключ</b> боту не нужен."
        ),
        Platform.TWITCH: f"Теперь отправь <b>Client Secret</b> для {label}:",
        Platform.KICK: f"Теперь отправь <b>Client Secret</b> для {label}:",
        Platform.YOUTUBE: f"Теперь отправь <b>Client Secret</b> для {label}:",
        Platform.TROVO: f"Теперь отправь <b>Client Secret</b> для {label}:",
    }
    return hints.get(platform, f"Теперь отправь <b>Client Secret</b> для {label}:")


def setup_instructions(platform: Platform) -> str:
    label = PLATFORM_LABELS[platform]

    texts = {
        Platform.TWITCH: (
            f"<b>{label} — создание приложения</b>\n\n"
            f"{server_requirement_note()}"
            "1. Открой https://dev.twitch.tv/console/apps\n"
            "2. <b>Register Your Application</b>\n"
            "3. Название — любое (например stream_tools)\n"
            "4. В поле <b>OAuth Redirect URLs</b> — URL из блока ниже → «Добавить»\n"
            "5. Category: <b>Broadcaster Suite</b> или Chat Bot\n"
            "6. Тип: <b>Конфиденциально</b> (Confidential)\n"
            "7. Создай → скопируй <b>Client ID</b> и <b>Client Secret</b>\n"
            "8. Отправь их боту по очереди"
        ),
        Platform.KICK: (
            f"<b>{label} — создание приложения</b>\n"
            "(<a href=\"https://docs.kick.com/getting-started/kick-apps-setup\">инструкция Kick</a>)\n\n"
            f"{server_requirement_note()}"
            "1. Аккаунт на kick.com (если ещё нет)\n"
            "2. <b>Включи 2FA</b> в настройках — без этого Developer недоступен\n"
            "3. Вкладка Developer:\n"
            "   https://kick.com/settings/developer\n"
            "4. <b>Create app</b> — OAuth-приложение для своего канала\n"
            "5. <b>Redirect URL</b> — строка «Для этого бота» ниже\n"
            "6. Scopes: <code>user:read</code> <code>channel:read</code> <code>channel:write</code>\n"
            "7. Скопируй <b>Client ID</b> и <b>Client Secret</b> → боту\n\n"
            "⚠️ Вход в аккаунт — ссылка от бота (<code>id.kick.com</code>)."
        ),
        Platform.YOUTUBE: (
            f"<b>{label}</b>\n\n"
            f"{server_requirement_note()}"
            "1. Google Cloud Console → проект\n"
            "2. OAuth consent screen → Credentials → Web client\n"
            "3. Authorized redirect URI — «Для этого бота» ниже\n"
            "4. YouTube Data API v3 включить\n"
            "5. Client ID и Secret → боту"
        ),
        Platform.VK: (
            f"<b>{label} — подключение</b>\n"
            "(<a href=\"https://dev.live.vkvideo.ru/docs/index\">VK Video Live DevAPI</a>)\n\n"
            f"{server_requirement_note()}"
            "❌ <b>Не</b> мини-приложение на dev.vk.com!\n\n"
            "1. https://dev.live.vkvideo.ru/apps → войти через VK ID\n"
            "2. Создай приложение (название любое)\n"
            "3. Вкладка <b>Настройки</b> → прокрути вниз → поле\n"
            "   «<i>Список допустимых URL для редиректа после авторизации</i>»\n"
            "   (не «URL для web-push»!)\n"
            "   Вставь <b>одну строку</b> — URL из блока «Для этого бота» ниже.\n"
            f"   Для этого бота вставь:\n"
            f"   <code>{redirect_url_for(Platform.VK)}</code>\n"
            "   → <b>Сохранить</b> в кабинете VK.\n"
            "4. После создания скопируй в бот:\n"
            "   • <b>ID приложения</b> → первым сообщением (Client ID)\n"
            "   • <b>Секретный ключ приложения</b> → вторым (Client Secret)\n"
            "   • <b>Публичный ключ</b> — <u>не нужен</u>, не отправляй\n"
            "5. Бот даст ссылку на <code>live.vkvideo.ru/app/oauth2/authorize</code> "
            "(OAuth DevAPI, <b>не</b> id.vk.ru!)\n\n"
            "⚠️ <b>«Сервис заблокирован»</b> на id.vk.ru — значит используется неверный OAuth. "
            "Нужен DevAPI-вход через live.vkvideo.ru.\n"
            "• Redirect URL — в списке редиректов (не web-push!), посимвольно как у бота\n"
            f"• <code>{get_settings().public_base_url.rstrip('/')}/health</code> "
            "должен отвечать <code>{\"ok\":true}</code> "
            "(иначе nginx 502 — бот не запущен: <code>./run.sh</code>)\n"
            "• Если всё верно — обращение в поддержку VK (домен в блоклисте)"
        ),
        Platform.TROVO: (
            f"<b>{label}</b>\n\n"
            f"{server_requirement_note()}"
            "1. https://developer.trovo.live → приложение\n"
            "2. Redirect URL — «Для этого бота» ниже\n"
            "3. Scopes: channel_details_self, channel_update_self\n"
            "4. Client ID и Secret → боту"
        ),
    }
    return texts[platform] + redirect_block(platform)
