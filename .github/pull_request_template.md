<!--
Pull requests target `dev`, not `main` (main only takes releases).
PR открывается в ветку `dev`, не в `main` (в main попадают только релизы).
-->

## Что сделано



## Как проверено

- [ ] `python -m pytest -q`
- [ ] Конфиг загружается: `TELEGRAM_BOT_TOKEN=x ROUTE_1_CHAT_ID=-1 python -c "from app.config import load_config; load_config('.env.example')"`
- [ ] Для изменений docker/конфига: `docker compose up -d --build` и бот стартует (логи чистые)
