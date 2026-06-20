import json

from model_tools import get_tool_definitions, handle_function_call
from tools.registry import registry


def test_side_effect_policy_rejects_external_message_without_runtime_authorization(monkeypatch):
    dispatched = False

    def fake_dispatch(*args, **kwargs):
        nonlocal dispatched
        dispatched = True
        return json.dumps({"success": True})

    monkeypatch.setattr("model_tools.registry.dispatch", fake_dispatch)
    monkeypatch.setattr("hermes_cli.plugins.has_hook", lambda name: False)
    monkeypatch.setattr("hermes_cli.plugins.get_pre_tool_call_block_message", lambda *a, **k: None)

    result = json.loads(
        handle_function_call(
            "send_message",
            {"target": "qqbot", "message": "hello"},
            task_id="side-effect-test",
            tool_call_id="call-send-1",
            session_id="session-1",
        )
    )

    assert dispatched is False
    assert result["status"] == "rejected_side_effect_policy"
    assert result["reason"] == "runtime_authorization_required"
    assert result["tool_name"] == "send_message"


def test_side_effect_policy_allows_external_message_with_runtime_authorization(monkeypatch):
    captured = {}

    def fake_dispatch(name, args, **kwargs):
        captured["name"] = name
        captured["args"] = args
        captured["kwargs"] = kwargs
        return json.dumps({"success": True, "sent": True})

    monkeypatch.setattr("model_tools.registry.dispatch", fake_dispatch)
    monkeypatch.setattr("hermes_cli.plugins.has_hook", lambda name: False)
    monkeypatch.setattr("hermes_cli.plugins.get_pre_tool_call_block_message", lambda *a, **k: None)

    result = json.loads(
        handle_function_call(
            "send_message",
            {"target": "qqbot", "message": "hello"},
            task_id="side-effect-test",
            tool_call_id="call-send-2",
            session_id="session-1",
            runtime_authorization={
                "source": "user_runtime_approval",
                "approved": True,
                "scope": ["external_message_send"],
                "tool_call_id": "call-send-2",
            },
        )
    )

    assert result["success"] is True
    assert captured["name"] == "send_message"
    assert captured["args"] == {"target": "qqbot", "message": "hello"}


def test_side_effect_policy_rejects_homeassistant_control_without_runtime_authorization(monkeypatch):
    monkeypatch.setattr("model_tools.registry.dispatch", lambda *a, **k: json.dumps({"success": True}))
    monkeypatch.setattr("hermes_cli.plugins.has_hook", lambda name: False)
    monkeypatch.setattr("hermes_cli.plugins.get_pre_tool_call_block_message", lambda *a, **k: None)

    result = json.loads(
        handle_function_call(
            "ha_call_service",
            {"domain": "light", "service": "turn_on", "entity_id": "light.kitchen"},
            task_id="side-effect-test",
            tool_call_id="call-ha-1",
            session_id="session-1",
        )
    )

    assert result["status"] == "rejected_side_effect_policy"
    assert result["side_effect_class"] == "smart_home_control"


def test_side_effect_policy_rejects_cron_create_without_runtime_authorization(monkeypatch):
    monkeypatch.setattr("model_tools.registry.dispatch", lambda *a, **k: json.dumps({"success": True}))
    monkeypatch.setattr("hermes_cli.plugins.has_hook", lambda name: False)
    monkeypatch.setattr("hermes_cli.plugins.get_pre_tool_call_block_message", lambda *a, **k: None)

    result = json.loads(
        handle_function_call(
            "cronjob",
            {"action": "create", "schedule": "every 1h", "prompt": "send update"},
            task_id="side-effect-test",
            tool_call_id="call-cron-1",
            session_id="session-1",
        )
    )

    assert result["status"] == "rejected_side_effect_policy"
    assert result["side_effect_class"] == "manage_schedule"


def test_side_effect_policy_does_not_expose_runtime_authorization_to_model_schema():
    # Availability checks are environment-dependent; register a tiny temporary
    # schema to prove internal runtime auth is not represented in definitions.
    registry.register(
        name="_side_effect_schema_probe",
        toolset="test_side_effect_policy",
        schema={
            "name": "_side_effect_schema_probe",
            "description": "probe",
            "parameters": {"type": "object", "properties": {"message": {"type": "string"}}},
        },
        handler=lambda args, **kw: json.dumps({"ok": True}),
        side_effects={"class": "external_message_send", "risk": "external_api_call"},
        artifact_outputs=[],
        override=True,
    )
    try:
        definitions = get_tool_definitions(enabled_toolsets=["test_side_effect_policy"], quiet_mode=True)
        schema_text = json.dumps(definitions, ensure_ascii=False)
    finally:
        registry.deregister("_side_effect_schema_probe")

    assert "runtime_authorization" not in schema_text
    assert "side_effect_policy" not in schema_text
    assert "approved" not in schema_text


def test_side_effect_policy_covers_spotify_mutating_tools():
    from tools.side_effect_policy import requires_runtime_authorization

    assert requires_runtime_authorization("spotify_playback", {"action": "play"}) is True
    assert requires_runtime_authorization("spotify_playback", {"action": "pause"}) is True
    assert requires_runtime_authorization("spotify_devices", {"action": "transfer"}) is True
    assert requires_runtime_authorization("spotify_queue", {"action": "add"}) is True
    assert requires_runtime_authorization("spotify_playlists", {"action": "create"}) is True
    assert requires_runtime_authorization("spotify_library", {"kind": "tracks", "action": "save"}) is True


def test_side_effect_policy_allows_spotify_read_only_actions():
    from tools.side_effect_policy import requires_runtime_authorization

    assert requires_runtime_authorization("spotify_playback", {"action": "get_state"}) is False
    assert requires_runtime_authorization("spotify_devices", {"action": "list"}) is False
    assert requires_runtime_authorization("spotify_search", {"query": "lofi"}) is False
