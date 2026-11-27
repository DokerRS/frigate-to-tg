# frigate-to-tg

Бот, который следит за алертами Frigate через его HTTP API и отправляет фото события в нужный
чат/топик Telegram. Видео — по запросу (кнопка «🎬 Видео» под фото). Группы камер Frigate можно
назначить конкретным топикам. Telegram доступен через HTTP-прокси.

## Возможности

- Опрос Frigate API `GET /api/events` (Frigate 0.14+) — MQTT не нужен.
- Фото события (snapshot, при отсутствии — thumbnail) с компактной подписью в две строки:
  `🚗 Car — balkon · zone` и `80% · 🕒 26.11.2025 20:13`. Отключается `CAPTION_CARD=false`
  (тогда используется простой `CAPTION_FORMAT`).
- Кнопка «🎬 Видео» → бот скачивает `clip.mp4` из Frigate и отправляет в чат
  (если больше `video_max_mb` — отправляется как документ).
- Кнопка «🔗 Открыть в Frigate» → ссылка на событие в веб-интерфейсе Frigate
  (`FRIGATE_PUBLIC_URL/review?id=<event_id>`). Для внешних адресов укажите `FRIGATE_PUBLIC_URL`.
- Маршрутизация: `группа камер / список камер → chat_id + thread_id (топик)`.
  Группы читаются прямо из конфига Frigate (`camera_groups`), плюс можно задать свои.
- Фильтры по объектам и минимальному score; одно сообщение на событие.
- HTTP/SOCKS-прокси для Telegram API.
- Docker Compose.

## Быстрый старт

1. Создайте бота у [@BotFather](https://t.me/BotFather), получите токен.
   Для отправки в топики бот должен быть добавлен в группу-форум и иметь право писать сообщения.
2. Скопируйте пример конфигурации:
   ```bash
   cp .env.example .env
   ```
   `.env` не попадает в git (`.gitignore`), поэтому токен и пароли пишете прямо в него.
   docker compose подхватывает `.env` автоматически (файл рядом с compose-файлом).
3. Заполните `.env`: токен бота, адрес Frigate, прокси Telegram, маршруты
   (см. ниже). `chat_id` чата узнайте командой `/chatid` (напишите боту в нужный чат/топик).
4. Запуск. Есть два варианта:

   **Вариант A — из готового образа из Docker Hub (рекомендуется, не нужен исходник и сборка):**
   ```bash
   docker compose -f docker-compose-prod.yml pull
   docker compose -f docker-compose-prod.yml up -d
   docker compose -f docker-compose-prod.yml logs -f
   ```
   Обновление — те же `pull` + `up -d` (или конкретная версия: `image: docker.io/dokerrs/frigate-to-tg:0.1.0`
   в `docker-compose-prod.yml`). CI публикует образы в `docker.io/dokerrs/frigate-to-tg` и
   `ghcr.io/dokerrs/frigate-to-tg` (теги `latest` и номер релиза; `dev` — сборки из ветки dev).

   **Вариант B — сборка из исходников локально:**
   ```bash
   docker compose up -d --build
   docker compose logs -f
   ```

Сетей external в compose нет: по умолчанию контейнер в своей сети, поэтому в `.env`
укажите прямой адрес Frigate (например `FRIGATE_URL=http://192.168.1.10:5000`). Если Frigate доступен
по имени контейнера — раскомментируйте блок `networks` в compose и подключите
контейнер к его сети (`docker network ls`).
Блок `logging` в compose ограничивает размер логов контейнера (json-file, 10 МБ × 3 файла).

## Конфигурация

Вся конфигурация — переменные окружения, которые читаются из `.env`
(полный пример с комментариями — [.env.example](.env.example)). Реальные переменные
окружения имеют приоритет над `.env`. Путь к файлу можно изменить переменной `ENV_PATH`.

Основные переменные:

```dotenv
# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_PROXY_URL=             # http://... или socks5://... (пусто = без прокси)

# Frigate
FRIGATE_URL=http://192.168.1.10:5000
#FRIGATE_PUBLIC_URL=http://frigate.example.com   # внешний адрес для кнопки «Открыть в Frigate»
#FRIGATE_USER=admin
#FRIGATE_PASSWORD=secret        # или #FRIGATE_TOKEN=<frigate api token>
FRIGATE_POLL_INTERVAL=3         # как часто (сек) опрашивать /api/events
FRIGATE_LOOKBACK=60             # за сколько секунд назад смотреть события при опросе

# Логи и поведение алертов
LOG_LEVEL=INFO                  # DEBUG | INFO | WARNING | ERROR
#LOG_FILE=/data/app.log         # дополнительный лог в файл (по умолчанию только stdout)
CAPTION_CARD=true               # компактная подпись под фото в две строки
TIMEZONE=Asia/Almaty            # таймзона времени в карточке
#SEND_VIDEO_BUTTON=true         # кнопка «Видео» под фото
#ALERT_MIN_SCORE=0.7            # общий минимальный score

# Группы камер
GROUPS_FROM_FRIGATE=true        # использовать camera_groups из Frigate
#GROUP_FRONT=front_door_cam,porch_cam   # своя группа (через запятую)

# Маршруты: чат + топик <- группы/камеры (нумерация произвольная)
ROUTE_1_CHAT_ID=-1001234567890
ROUTE_1_THREAD_ID=42            # 0 / отсутствует => без топика
ROUTE_1_TITLE=Передняя дверь
ROUTE_1_GROUPS=front            # группы (frigate или GROUP_*)
#ROUTE_1_CAMERAS=driveway_cam   # можно конкретные камеры (через запятую)
#ROUTE_1_OBJECTS=person,car     # фильтр по объектам
#ROUTE_1_MIN_SCORE=0.7
#ROUTE_1_SEND_VIDEO=true        # кнопка «Видео» (по умолчанию — из SEND_VIDEO_BUTTON)
```

Маршрут без `GROUPS` и `CAMERAS` — «все камеры». Если группа не найдена, бот предупредит в логе
(проверьте, что `GROUPS_FROM_FRIGATE=true` и имя группы совпадает с `camera_groups` в Frigate;
в API используются внутренние id камер, а не `friendly_name`).

Команды бота: `/chatid` (id чата и топика), `/groups` (известные группы камер),
`/refresh` (перечитать группы из Frigate), `/debug [DEBUG|INFO|WARNING|ERROR]` (сменить
уровень логирования на лету), `/help`.

## Логи

Основной лог — stdout контейнера (`docker compose logs -f`). Настройки — переменные
`LOG_LEVEL`, `LOG_FILE`, `LOG_HTTP_DEBUG`. При `LOG_LEVEL=DEBUG` в лог пишется каждое новое
событие Frigate (camera/label/score) и причины пропуска алертов. Менять уровень можно
без перезапуска: `/debug DEBUG`.

## CI/CD

- **CI** (`.github/workflows/ci.yml`) — на PR и пуш в `main`/`dev`: pytest + smoke-сборка образа.
- **Релиз** — пуш тега (например `v0.1.0`) собирает multi-arch образ (amd64/arm64), публикует
  `latest` и тег в GHCR и Docker Hub, создаёт GitHub Release.
- **Dev-образ** — пуш в `dev` публикует тег `dev`.

Секреты в Settings → Secrets and variables → Actions: `TELEGRAM_TOKEN` + `TELEGRAM_CHAT_ID`
(уведомления о сборках), `DOCKERHUB_USERNAME` (имя пользователя Docker Hub) + `DOCKERHUB_TOKEN`
(access token; без него пуш только в GHCR). Образ публикуется как
`docker.io/<DOCKERHUB_USERNAME>/frigate-to-tg`. GHCR работает через встроенный `GITHUB_TOKEN`.

## Разработка

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt pytest
python -m pytest
copy .env.example .env && python -m app   # или задайте переменные окружения напрямую
```