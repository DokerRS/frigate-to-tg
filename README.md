# frigate-to-tg

Бот, который получает алерты Frigate по MQTT и отправляет фото события в нужный чат/топик
Telegram. Видео — по запросу (кнопка «🎬 Видео» под фото). Группы камер Frigate можно
назначить конкретным топикам. Telegram доступен через HTTP-прокси.

## Возможности

- Подписка на MQTT-топик `frigate/events` (Frigate 0.14+).
- Фото события (snapshot, при отсутствии — thumbnail) с компактной подписью в две строки:
  `🚗 Car — balkon · zone` и `80% · 🕒 26.11.2025 20:13`. Отключается `alerts.caption_card: false`
  (тогда используется простой `caption_format`).
- Кнопка «🎬 Видео» → бот скачивает `clip.mp4` из Frigate и отправляет в чат
  (если больше `video_max_mb` — отправляется как документ).
- Кнопка «🔗 Открыть в Frigate» → ссылка на событие в веб-интерфейсе Frigate
  (`frigate.public_url/review?id=<event_id>`). Для внешних адресов укажите `public_url`.
- Маршрутизация: `группа камер / список камер → chat_id + thread_id (топик)`.
  Группы читаются прямо из конфига Frigate (`camera_groups`), плюс можно задать свои.
- Фильтры по объектам и минимальному score; одно сообщение на событие.
- HTTP/SOCKS-прокси для Telegram API.
- Docker Compose.

## Быстрый старт

1. Создайте бота у [@BotFather](https://t.me/BotFather), получите токен.
   Для отправки в топики бот должен быть добавлен в группу-форум и иметь право писать сообщения.
2. Скопируйте конфиг:
   ```bash
   cp config/config.example.yaml config/config.yaml
   ```
   `config/config.yaml` не попадает в git (`.gitignore`), поэтому токен и пароли пишете прямо в него.
3. Заполните `config/config.yaml`: токен бота, адреса Frigate/MQTT, прокси Telegram, маршруты
   (см. ниже). `chat_id` чата узнайте командой `/chatid` (напишите боту в нужный чат/топик).
4. Запуск:
   ```bash
   docker compose up -d
   docker compose logs -f
   ```

Сетей external в compose нет: по умолчанию контейнер в своей сети, поэтому в `config.yaml`
укажите прямые адреса Frigate/MQTT (например `http://192.168.1.10:5000`). Если Frigate/MQTT
доступны по именам контейнеров — раскомментируйте блок `networks` в compose и подключите
контейнер к их сети (`docker network ls`).
Блок `logging` в compose ограничивает размер логов контейнера (json-file, 10 МБ × 3 файла).

## Конфигурация

Единственный файл — `config/config.yaml`. Значения `${VAR}` и `${VAR:-default}`
при желании можно подставлять из переменных окружения.

```yaml
logging:
  level: INFO               # DEBUG | INFO | WARNING | ERROR
  # file: /data/app.log     # дополнительный лог в файл (по умолчанию только stdout/docker logs)
  # http_debug: false       # true = отладочные логи HTTP-запросов (httpx/httpcore)

frigate:
  url: http://frigate:5000
  # public_url: http://192.168.1.10:5000  # внешний адрес для кнопки «Открыть в Frigate»
  # auth: { user: ..., password: ... }   # basic auth
  # auth: { token: ... }                 # или токен Frigate

mqtt:
  host: mqtt
  port: 1883
  prefix: frigate           # события приходят в <prefix>/events

telegram:
  bot_token: "123456:ABC-DEF..."
  proxy_url: ""               # http://... или socks5://... (пусто = без прокси)

alerts:
  caption_card: true          # компактная подпись под фото в две строки (по умолчанию true)
  timezone: Asia/Almaty       # таймзона времени в карточке
  # caption_format: "{camera}: {label} — {score}%"  # простая подпись (caption_card: false)

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
`/refresh` (перечитать группы из Frigate), `/debug [DEBUG|INFO|WARNING|ERROR]` (сменить
уровень логирования на лету), `/help`.

## Логи

Основной лог — stdout контейнера (`docker compose logs -f`). Настройки — в секции `logging`
конфига: уровень, файл, отладка HTTP. При `level: DEBUG` в лог пишется каждое полученное
MQTT-событие (camera/label/score/topik) и причины пропуска алертов. Менять уровень можно
без перезапуска: `/debug DEBUG`.

## Разработка

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt pytest
python -m pytest
CONFIG_PATH=config/config.yaml python -m app
```