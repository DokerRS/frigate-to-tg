import pytest

from app.config import ConfigError, load_config


def load(monkeypatch, **env):
    """Грузит конфиг из переменных окружения (без .env файла)."""
    monkeypatch.setenv("ENV_PATH", "nonexistent.env")
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    return load_config()


def test_minimal_config(monkeypatch):
    cfg = load(monkeypatch, TELEGRAM_BOT_TOKEN="tok", ROUTE_1_CHAT_ID=-1001, ROUTE_1_GROUPS="front")
    assert cfg.telegram.bot_token == "tok"
    assert cfg.telegram.proxy_url is None
    assert cfg.routes[0].groups == ("front",)
    assert cfg.routes[0].thread_id is None


def test_env_file_and_defaults(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        """
# комментарий
TELEGRAM_BOT_TOKEN="tok"
TELEGRAM_PROXY_URL=http://proxy:3128
FRIGATE_POLL_INTERVAL=5
ROUTE_1_CHAT_ID=-1
ROUTE_1_THREAD_ID=0
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    cfg = load_config(env_file)
    assert cfg.telegram.bot_token == "tok"
    assert cfg.telegram.proxy_url == "http://proxy:3128"
    assert cfg.frigate.poll_interval == 5.0
    assert cfg.routes[0].thread_id is None  # 0 трактуется как "без топика"


def test_real_env_overrides_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=from_file\nROUTE_1_CHAT_ID=-1\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "from_env")
    cfg = load_config(env_file)
    assert cfg.telegram.bot_token == "from_env"


def test_missing_token_fails(monkeypatch):
    monkeypatch.setenv("ENV_PATH", "nonexistent.env")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("ROUTE_1_CHAT_ID", "-1")
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_config()


def test_missing_routes_fails(monkeypatch):
    monkeypatch.setenv("ENV_PATH", "nonexistent.env")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    for k in list(__import__("os").environ):
        if k.startswith("ROUTE_"):
            monkeypatch.delenv(k)
    with pytest.raises(ConfigError, match="ROUTE_1_CHAT_ID"):
        load_config()


def test_route_without_target_defaults_to_all(monkeypatch):
    cfg = load(monkeypatch, TELEGRAM_BOT_TOKEN="tok", ROUTE_1_CHAT_ID=-1002)
    assert cfg.routes[0].groups == ()
    assert cfg.routes[0].cameras == ()
    assert cfg.routes[0].title == "все камеры"


def test_multiple_routes_groups_and_types(monkeypatch):
    cfg = load(
        monkeypatch,
        TELEGRAM_BOT_TOKEN="tok",
        ROUTE_2_CHAT_ID=-1002,
        ROUTE_2_THREAD_ID=42,
        ROUTE_2_TITLE="Передняя дверь",
        ROUTE_2_GROUPS="front,back",
        ROUTE_2_OBJECTS="Person, CAR ",
        ROUTE_2_MIN_SCORE=0.7,
        ROUTE_2_SEND_VIDEO="false",
        ROUTE_1_CHAT_ID=-1001,
        ROUTE_1_CAMERAS="driveway_cam",
        GROUP_FRONT="front_door_cam,porch_cam",
        GROUPS_FROM_FRIGATE="false",
    )
    # маршруты в порядке номеров
    assert [r.chat_id for r in cfg.routes] == [-1001, -1002]
    r = cfg.routes[1]
    assert r.thread_id == 42
    assert r.groups == ("front", "back")
    assert r.objects == ("person", "car")
    assert r.min_score == 0.7
    assert r.send_video is False
    assert cfg.routes[0].send_video is None  # не задан -> наследует общий флаг
    assert cfg.groups.extra == {"front": ["front_door_cam", "porch_cam"]}
    assert cfg.groups.from_frigate is False


def test_bad_values_fail(monkeypatch):
    with pytest.raises(ConfigError, match="ROUTE_1_CHAT_ID"):
        load(monkeypatch, TELEGRAM_BOT_TOKEN="tok", ROUTE_1_CHAT_ID="not-a-number")
    with pytest.raises(ConfigError, match="FRIGATE_POLL_INTERVAL"):
        load(monkeypatch, TELEGRAM_BOT_TOKEN="tok", ROUTE_1_CHAT_ID=-1, FRIGATE_POLL_INTERVAL="abc")
    monkeypatch.delenv("FRIGATE_POLL_INTERVAL")
    with pytest.raises(ConfigError, match="CAPTION_CARD"):
        load(monkeypatch, TELEGRAM_BOT_TOKEN="tok", ROUTE_1_CHAT_ID=-1, CAPTION_CARD="maybe")


def test_env_file_syntax_error(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("TOKEN\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="строка 1"):
        load_config(env_file)
