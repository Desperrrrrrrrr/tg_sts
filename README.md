# StreamSync TG

**Привет!** Меня зовут [Desper](https://twitch.tv/desper_i9_) — я автор идеи этого бота. Сделал его с помощью ИИ, потому что устал вручную менять категорию и название стрима на каждой площадке перед эфиром. Теперь всё делается из Telegram — даже с телефона, пока идёшь к ПК.

Если Telegram не работает, то загляни на [gl-hf.ru](https://gl-hf.ru) (в планах ещё и прокси для TG).  
**Критика, баги и идеи приветствуются** — пиши в [личку Telegram](https://t.me/Desperrrrrrrrr). Если есть идея фичи — попробуем вместе, я только за.

На стримах у меня есть счётчики серии прохождений **Dark Souls** (сейчас для первых двух частей; третью ещё не начинал — счётчик появится позже). Заходи на [twitch.tv/desper_i9](https://twitch.tv/desper_i9) — там и чат, и атмосфера.

Хочешь отблагодарить — welcome на эфир или [DonationAlerts](https://www.donationalerts.com/r/desper_i9). Даже маленький донат — как «спасибо, что не заставляешь меня кликать по пяти сайтам перед стартом».

---

Telegram-бот: смена **игры (категории)** и **названия стрима** на Twitch, Kick, VK Video Live (+ задел под YouTube и Trovo) и анонсы в канале/группе.

## Что проверено и работает (на 100%)

| Площадка | Категория / игра | Название стрима | OAuth | Примечание |
|----------|------------------|-----------------|-------|------------|
| **Twitch** | ✅ | ✅ | ✅ | Поиск игр, лимит 140 символов для описания стрима |
| **Kick** | ✅ | ✅ | ✅ | Поиск с алиасами (cs2 → Counter-Strike 2) |
| **VK Video Live** | ✅ | ✅ | ✅ + session-токен | См. раздел «VK» ниже |
| YouTube | ⏸ | ⏸ | сделано, но не проверено | Не тестировалось, отложено |
| Trovo | ⏸ | ⏸ | сделано, но не проверено | Площадка под вопросом, отложено |

## Что сделали под капотом (кратко)

### Twitch

- Поиск игр через **Helix `/games` + `/search/categories`**: у Twitch «Counter-Strike 2» не находится по имени в API — это `game_id=32399`, в ответе имя «Counter-Strike».
- **Алиасы** (`cs2`, `counter strike 2` → Counter-Strike 2) и ранжирование, чтобы не предлагать CS2D и «Counter-Strike Online 2».
- **Название стрима** — только лимит **140 символов** (как на сайте), без лишней обрезки по байтам UTF-8.

### Kick

- Поиск по **нескольким вариантам запроса** + общее ранжирование (как на VK).
- Короткий запрос `cs2` больше не матчится на **CS2D** по подстроке. (матчится на самом деле, пока не знаю почему, но иногда всплывают не правильные варианты. Но правильный вариант присутствует рядом с CS2D к примеру)
- Смена категории и названия через **Public API** (`PATCH /channels`) — отдельные поля, название не затирается.

### VK Video Live (оказался самым противным и не поддающимся по началу, пришлось поразбираться)

- **OAuth DevAPI** — чтение, поиск категорий; **запись** (смена игры/названия) через web API `PUT /channel/{slug}/manage/stream`.
- **Session-токен** из `localStorage` браузера (ключ `auth` на live.vkvideo.ru) — кнопка **«🔑 Session-токен VK»** в боте после подключения.
- **Slug канала** — часть URL после `live.vkvideo.ru/` (например `desper_i9`).
- При смене **только категории** бот **подтягивает текущее название** и отправляет его вместе с `category_id` — иначе VK сбрасывает title.

## Автозапуск после перезагрузки сервера

Один раз на VPS (из каталога проекта, **не от root** напрямую — через `sudo`):

```bash
cd /home/%user%/tg_sts   # свой путь к каталогу
chmod +x deploy/install-service.sh
sudo ./deploy/install-service.sh
```

Скрипт создаёт systemd-сервис `streamsync`, включает автозапуск и перезапускает бота.

Полезные команды:

```bash
sudo systemctl status streamsync      # статус
journalctl -u streamsync -f           # логи в реальном времени
sudo systemctl restart streamsync       # перезапуск после правок кода
sudo systemctl stop streamsync          # остановить (ручной ./run.sh тогда не нужен параллельно)
```

**Важно:** не запускай `./run.sh` и systemd **одновременно** — будет два экземпляра бота. После установки сервиса пользуйся только `systemctl`.

Файл юнита: [`deploy/streamsync.service`](deploy/streamsync.service)

---

## Кто что настраивает

| | Деплойер (поднял бота с GitHub) | Стример (пишет боту) |
|---|-----------------------------------|----------------------|
| Сервер / VPS | ✅ | ❌ |
| `TELEGRAM_BOT_TOKEN` | ✅ | ❌ |
| Домен + HTTPS (Let's Encrypt) | ✅ | ❌ |
| `PUBLIC_BASE_URL` | ✅ | ❌ |
| Client ID / Secret площадок | ❌ | ✅ через `/setup` в боте |
| Авторизация аккаунта | ❌ | ✅ по ссылке в боте |
| VK session-токен (для записи) | ❌ | ✅ кнопка в боте |

## Быстрый старт (деплойер)

```bash
git clone <repo> tg_sts && cd tg_sts
python3 -m venv strem_switcher
source strem_switcher/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполни TELEGRAM_BOT_TOKEN, TOKEN_ENCRYPTION_KEY, PUBLIC_BASE_URL
./run.sh
# или для автозапуска: sudo ./deploy/install-service.sh
```

Бот слушает **локально** `http://127.0.0.1:8080` (или `0.0.0.0:8080` — см. `.env`). Снаружи к нему подключается nginx с SSL.

## HTTPS (обязательно для Twitch на VPS)

Twitch принимает redirect URL только:
- `http://localhost:8080/...` — бот на этом же компьютере
- `https://домен/...` — бот на сервере

### Схема

```
Браузер → https://сайт.ru/oauth/twitch (у вас свой вариант, тут как пример)
              ↓
         nginx :443 (SSL)
              ↓
         бот :8080
```

### Вариант A — уже есть сайт и сертификат (рекомендуется)

Добавь **два location** в существующий `server { ... }` на `:443`.  
Сниппет: [`deploy/nginx/existing-site-locations.conf`](deploy/nginx/existing-site-locations.conf)

```nginx
    location ^~ /oauth/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location = /health {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

В `.env`:

```env
PUBLIC_BASE_URL=https://сайт.ru
```

Проверка: `curl https://сайт.ru/health` → `{"ok":true}`

**Не запускай** `deploy/setup-https.sh`, если nginx и SSL уже настроены.

### Вариант B — отдельный поддомен с нуля

```bash
sudo ./deploy/setup-https.sh stream.example.com
PUBLIC_BASE_URL=https://stream.example.com
```

Пример vhost: [`deploy/nginx/streamsync.conf.example`](deploy/nginx/streamsync.conf.example)

## Redirect URL для площадок

Бот покажет точную строку при `/setup`. Пример для сайт.ru:

```
https://сайт.ru/oauth/twitch
https://сайт.ru/oauth/kick
https://сайт.ru/oauth/youtube
https://сайт.ru/oauth/vk
https://сайт.ru/oauth/trovo
```

`PUBLIC_BASE_URL` и Redirect URL в консоли разработчика должны **совпадать** (оба `https://`, без порта).

## Пользователь в Telegram

1. `/start` или `/setup` — выбор площадок
2. Client ID + Client Secret (бот подскажет)
3. Авторизация по ссылке
4. **VK:** slug канала + по желанию session-токен из браузера
5. Канал для анонсов (переслать сообщение)
6. Кнопки: **🎮 Игра — везде**, **✏️ Название — везде**, отдельные площадки, **📊 Статус**

После смены игры бот спросит название стрима — можно нажать **⏭ Пропустить** (категория уже применена).

## Анонсы

- Старт: обложка, фраза, кнопки площадок
- Конец: бот спрашивает итог и дату следующего эфира (`/skip` или кнопка пропуска)
- Пост о старте удаляется через 10 мин, о конце — через 1 час

## Безопасность (коротко)

- В логах могут быть `GET /` → 404 от интернет-сканеров — это **не взлом**, просто фоновый шум.
- Снаружи открыты только `/oauth/*` и `/health`; секреты в `.env`, токены в БД шифруются (`TOKEN_ENCRYPTION_KEY`).

## Миграция БД

При обновлении схемы: `rm -f data/bot.db` и снова `/setup` (или бэкап перед удалением).

---

**Контакты:** [Telegram @Desperrrrrrrrr](https://t.me/Desperrrrrrrrr) · [Twitch](https://twitch.tv/desper_i9) · [DonationAlerts](https://www.donationalerts.com/r/desper_i9) · [gl-hf.ru](https://gl-hf.ru)
