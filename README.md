# frigate-to-tg

Бот, который получает алерты Frigate по MQTT и отправляет фото события в нужный чат/топик
Telegram. Видео — по запросу (кнопка «🎬 Видео» под фото). Группы камер Frigate можно
назначить конкретным топикам. Telegram доступен через HTTP-прокси.

## Возможности

- Подписка на MQTT-топик `frigate/events` (Frigate 0.14+).
- Фото события (snapshot, при отсутствии — thumbnail) с подписью `{camera}: {label} — {score}%`.
- Кнопка «🎬 Видео» → бот скачивает `clip.mp4` из Frigate и отправляет в чат
  (если больше `video_max_mb` — отправляется как документ).
- Маршрутизация: `группа камер / список камер → chat_id + thread_id (топик)`.
  Группы читаются прямо из конфига Frigate (`camera_groups`), плюс можно задать свои.
- Фильтры по объектам и минимальному score; одно сообщение на событие.
- HTTP/SOCKS-прокси для Telegram API.
- Docker Compose.

## Быстрый старт

1. Создайте бота у [@BotFather](https://t.me/BotFather), получите токен.
   Для отправки в топики бот должен быть добавлен в группу-форум и иметь право писать сообщения.
2. Скопируйте файлы:
   ```bash
   cp .env.example .env
   cp config/config.example.yaml config/config.yaml
   ```
3. Заполните `.env` (в нём только секреты, остальное — в `config/config.yaml`):
   - `TELEGRAM_BOT_TOKEN` — токен бота;
   - `TELEGRAM_PROXY_URL` — например `http://user:pass@192.168.1.5:3128` (пусто = без прокси).
4. Настройте `config/config.yaml`: адреса Frigate/MQTT и маршруты (см. ниже).
   `chat_id` чата узнайте командой `/chatid` (напишите боту в нужный чат/топик).
5. Запуск:
   ```bash
   docker compose up -d
   docker compose logs -f
   ```

В `docker-compose.yml` указаны сети `frigate_default` и `mqtt_default` (external). Замените
имена на свои (`docker network ls`) или укажите прямые адреса в `.env`.

## Конфигурация

Значения `${VAR}` и `${VAR:-default}` в YAML подставляются из переменных окружения.

```yaml
frigate:
  url: http://frigate:5000
  # auth: { user: ..., password: ... }   # basic auth
  # auth: { token: ... }                 # или токен Frigate

mqtt:
  host: mqtt
  port: 1883
  prefix: frigate           # события приходят в <prefix>/events

telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}
  proxy_url: ${TELEGRAM_PROXY_URL:-}   # http://... или socks5://...

groups:
  from_frigate: true          # использовать camera_groups из Frigate
  extra:
    front: [front_door_cam, porch_cam]

routes:
  - chat_id: -1001234567890
    thread_id: 42             # 0 / отсутствует => без топика
    title: "Передняя дверь"
    groups: [front]           # группы (frigate или extra)
    # cameras: [driveway_cam] # можно конкретные камеры
    # objects: [person, car]  # фильтр по объектам
    # min_score: 0.7
    # send_video: true        # кнопка «Видео» (по умолчанию — из alerts)
```

Маршрут без `groups` и `cameras` — «все камеры». Если группа не найдена, бот предупредит в логе
(проверьте, что `groups.from_frigate: true` и имя группы совпадает с `camera_groups` в Frigate;
в MQTT используются внутренние id камер, а не `friendly_name`).

Команды бота: `/chatid` (id чата и топика), `/groups` (известные группы камер),
`/refresh` (перечитать группы из Frigate), `/help`.

## Разработка

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt pytest
python -m pytest
CONFIG_PATH=config/config.yaml python -m app
```