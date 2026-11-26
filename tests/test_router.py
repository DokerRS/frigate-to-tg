from app.config import AlertsConfig, AppConfig, FrigateConfig, GroupsConfig, MqttConfig, Route, TelegramConfig
from app.router import Router, parse_event


def make_cfg(routes, groups_extra=None, min_score=0.0):
    return AppConfig(
        frigate=FrigateConfig(),
        mqtt=MqttConfig(),
        telegram=TelegramConfig(bot_token="t"),
        alerts=AlertsConfig(min_score=min_score),
        groups=GroupsConfig(from_frigate=False, extra=groups_extra or {}),
        routes=routes,
    )


EVENT = {
    "type": "update",
    "after": {
        "id": "123.4-abc",
        "camera": "front_door",
        "label": "Person",
        "top_score": 0.9,
        "has_snapshot": True,
        "has_clip": True,
        "entered_zones": ["driveway"],
        "start_time": 1.0,
        "snapshot": {"frame_time": 1.0},
    },
}


def test_parse_event():
    ev = parse_event(EVENT)
    assert ev.event_id == "123.4-abc"
    assert ev.camera == "front_door"
    assert ev.label == "person"
    assert ev.score == 0.9
    assert ev.has_snapshot and ev.has_clip
    assert ev.action == "update"


def test_parse_event_rejects_garbage():
    assert parse_event({}) is None
    assert parse_event({"type": "new"}) is None


def test_group_route_matches_only_group_cameras():
    cfg = make_cfg([Route(chat_id=-1, thread_id=42, groups=["front"])], groups_extra={"front": ["front_door"]})
    router = Router(cfg)
    assert router.match(parse_event(EVENT)) == [cfg.routes[0]]
    other = dict(EVENT["after"], camera="back_yard")
    assert router.match(parse_event(dict(EVENT, after=other))) == []


def test_frigate_groups_used():
    cfg = make_cfg([Route(chat_id=-1, groups=["yard"])])
    router = Router(cfg, frigate_groups={"yard": ["back_yard"]})
    ev = parse_event(dict(EVENT, after=dict(EVENT["after"], camera="back_yard")))
    assert len(router.match(ev)) == 1


def test_catchall_route():
    cfg = make_cfg([Route(chat_id=-1)])
    router = Router(cfg)
    assert len(router.match(parse_event(EVENT))) == 1


def test_object_and_score_filters():
    cfg = make_cfg(
        [
            Route(chat_id=-1, objects=["car"]),
            Route(chat_id=-2, min_score=0.95),
            Route(chat_id=-3, objects=["person"], min_score=0.5),
        ]
    )
    router = Router(cfg)
    matched = {r.chat_id for r in router.match(parse_event(EVENT))}
    assert matched == {-3}


def test_global_min_score():
    cfg = make_cfg([Route(chat_id=-1)], min_score=0.95)
    router = Router(cfg)
    assert router.match(parse_event(EVENT)) == []


def test_caption_format():
    ev = parse_event(EVENT)
    assert ev.caption("{camera}: {label} — {score}%") == "front_door: person — 90%"
