import re

from src.config import get_settings
from src.db.models import Platform

_IPV4_RE = re.compile(r"^\w+://\d{1,3}(?:\.\d{1,3}){3}")


def redirect_url_for(platform: Platform) -> str:
    return f"{get_settings().oauth_callback_base}/{platform.value}"


def public_base_url_configured() -> bool:
    url = get_settings().public_base_url.strip().rstrip("/").lower()
    if not url:
        return False
    placeholders = (
        "your-domain.com",
        "example.com",
        "stream.example.com",
        "твой-домен",
    )
    return not any(p in url for p in placeholders)


def needs_https_for_oauth() -> bool:
    """Twitch/Kick и др. требуют HTTPS на домене, кроме localhost."""
    url = get_settings().public_base_url.strip().lower()
    if "localhost" in url or "127.0.0.1" in url:
        return False
    if url.startswith("http://"):
        return True
    if _IPV4_RE.match(url) or ":8080" in url:
        return True
    return False


def oauth_https_hint() -> str:
    url = get_settings().public_base_url.strip().lower()
    extra = ""
    if _IPV4_RE.match(url):
        extra = (
            "Сейчас указан <b>IP</b> — Let's Encrypt выдаёт сертификат только на <b>домен</b>.\n\n"
        )
    elif url.startswith("https://") and ":8080" in url:
        extra = (
            "Сейчас в URL есть <code>:8080</code> — снаружи нужен <b>443 без порта</b> "
            "(nginx проксирует на локальный 8080).\n\n"
        )
    return (
        "⚠️ <b>Twitch требует HTTPS на домене</b> (кроме <code>localhost</code>).\n\n"
        + extra
        + "Бот слушает <code>:8080</code> без SSL — это нормально. "
        "HTTPS даёт <b>nginx + Let's Encrypt</b> на порту 443.\n\n"
        "<b>Настройка (один раз, деплойер):</b>\n"
        "Если nginx и SSL уже есть — добавь <code>location ^~ /oauth/</code> "
        "и <code>location = /health</code> → <code>127.0.0.1:8080</code> "
        "(сниппет: <code>deploy/nginx/existing-site-locations.conf</code>).\n"
        "В <code>.env</code>: <code>PUBLIC_BASE_URL=https://твой-домен.ru</code> (без :8080).\n"
        "Перезапуск: <code>sudo nginx -t && sudo systemctl reload nginx</code>, затем <code>./run.sh</code>.\n\n"
        "Скрипт <code>setup-https.sh</code> — только для пустого VPS без своего сайта.\n"
        "Подробнее: <code>README.md</code> → HTTPS."
    )


def public_url_setup_hint() -> str:
    base = get_settings().public_base_url.rstrip("/")
    return (
        "⚠️ <b>Сначала настрой адрес сервера</b> (тот, кто запустил бота с GitHub).\n\n"
        "В файле <code>.env</code> на сервере укажи реальный <code>PUBLIC_BASE_URL</code> — "
        "это адрес, по которому бот доступен из интернета.\n\n"
        f"Сейчас: <code>{base}</code>\n\n"
        "<b>Примеры PUBLIC_BASE_URL:</b>\n"
        "• С Let's Encrypt: <code>https://stream.mysite.ru</code> (без :8080!)\n"
        "• Тест на этом ПК: <code>http://localhost:8080</code>\n\n"
        "<b>Важно:</b> для VPS нужен домен + HTTPS. Голый IP с http Twitch не примет.\n"
        "Схема: интернет → nginx:443 (SSL) → бот:8080\n\n"
        "После смены — перезапусти <code>./run.sh</code> и снова /setup.\n\n"
        "В Twitch в поле <b>OAuth Redirect URL</b> вставляй строку, которую бот покажет ниже — "
        "она должна <b>совпадать посимвольно</b>."
    )
