<!--
Pull requests target `dev`, not `main` (main only takes releases).
PR открывается в ветку `dev`, не в `main` (в main попадают только релизы).
-->

## Что сделано



## Как проверено

- [ ] `python -m pytest -q`
- [ ] Конфиг загружается: `python -c "from app.config import load_config; load_config('config/config.example.yaml')"`
- [ ] Для изменений docker/конфига: `docker compose up -d --build` и бот стартует (логи чистые)
