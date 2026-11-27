import os

import pytest

from app.config import ConfigError, load_config


def write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_minimal_config(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    p = write(tmp_path, """
telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}
routes:
  - chat_id: -1001
    groups: [front]
""")
    cfg = load_config(p)
    assert cfg.telegram.bot_token == "tok"
    assert cfg.telegram.proxy_url is None
    assert cfg.routes[0].groups == ("front",)
    assert cfg.routes[0].thread_id is None


def test_env_default_and_proxy(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_PROXY_URL", "http://proxy:3128")
    p = write(tmp_path, """
telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}
  proxy_url: ${TELEGRAM_PROXY_URL:-}
frigate:
  url: http://frigate:5000
  poll_interval: ${POLL_INTERVAL:-5}
routes:
  - chat_id: -1
    thread_id: ${TG_TOPIC:-0}
""")
    cfg = load_config(p)
    assert cfg.telegram.proxy_url == "http://proxy:3128"
    assert cfg.frigate.poll_interval == 5.0
    assert cfg.routes[0].thread_id is None  # 0 трактуется как "без топика"


def test_missing_token_fails(tmp_path):
    p = write(tmp_path, "routes:\n  - chat_id: -1\n")
    with pytest.raises(ConfigError, match="bot_token"):
        load_config(p)


def test_route_without_target_defaults_to_all(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    p = write(tmp_path, """
telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}
routes:
  - chat_id: -1002
""")
    cfg = load_config(p)
    assert cfg.routes[0].groups == ()
    assert cfg.routes[0].cameras == ()


def test_bad_route_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    p = write(tmp_path, """
telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}
routes:
  - chat_id: not-a-number
""")
    with pytest.raises(ConfigError):
        load_config(p)
