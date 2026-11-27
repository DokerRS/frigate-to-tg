from app.bot import AlertBot
from app.config import AlertsConfig, AppConfig, FrigateConfig, GroupsConfig, Route, TelegramConfig
from app.router import parse_event

EVENT_RAW = {
    "id": "1700.4-abc",
    "camera": "front_door",
    "label": "Person",
    "top_score": 0.9,
    "has_snapshot": True,
    "has_clip": True,
    "zones": ["driveway"],
    "start_time": 1.0,
}

EVENT = parse_event(EVENT_RAW)


def make_bot(public_url=None, url="http://frigate:5000"):
    cfg = AppConfig(
        frigate=FrigateConfig(url=url, public_url=public_url),
        telegram=TelegramConfig(bot_token="t"),
        alerts=AlertsConfig(),
        groups=GroupsConfig(from_frigate=False),
        routes=[Route(chat_id=-1)],
    )
    return AlertBot(cfg, frigate=None, tg=None, router=None)  # type: ignore[arg-type]


def test_markup_video_and_link_rows():
    markup = make_bot()._markup(EVENT, show_video=True)
    rows = markup["inline_keyboard"]
    assert rows[0][0]["text"] == "🎬 Видео"
    assert rows[0][0]["callback_data"] == "v:1700.4-abc"
    assert rows[1][0]["url"] == "http://frigate:5000/review?id=1700.4-abc"


def test_markup_uses_public_url():
    markup = make_bot(public_url="http://192.168.1.10:5000/")._markup(EVENT, show_video=False)
    rows = markup["inline_keyboard"]
    assert len(rows) == 1
    assert rows[0][0]["url"] == "http://192.168.1.10:5000/review?id=1700.4-abc"


def test_markup_no_video_without_clip():
    raw = {**EVENT_RAW, "has_clip": False}
    ev = parse_event(raw)
    markup = make_bot()._markup(ev, show_video=True)
    assert all("url" in r[0] for r in markup["inline_keyboard"])
    assert len(markup["inline_keyboard"]) == 1
