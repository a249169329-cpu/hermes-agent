import json


def test_browser_snapshot_model_context_is_not_wrapped_in_this_slice():
    from model_tools import _wrap_tool_result_for_model_context
    from tools import browser_tool  # noqa: F401 - ensure registry registration

    raw = json.dumps({"success": True, "snapshot": "@e1 link"})

    assert _wrap_tool_result_for_model_context("browser_snapshot", raw) == raw


def test_browser_console_model_context_is_wrapped_and_bounded():
    from model_tools import _wrap_tool_result_for_model_context
    from tools import browser_tool  # noqa: F401 - ensure registry registration

    raw = json.dumps({
        "success": True,
        "console_messages": [
            {"type": "log", "text": "x" * 7000, "source": "console"},
            {"type": "error", "text": "short error", "source": "console"},
        ],
        "js_errors": [{"message": "boom", "source": "exception"}],
        "total_messages": 2,
        "total_errors": 1,
    })

    wrapped = json.loads(_wrap_tool_result_for_model_context("browser_console", raw))

    assert wrapped["tool_name"] == "browser_console"
    assert wrapped["tool_class"] == "browser"
    assert wrapped["success"] is True
    assert wrapped["summary"] == "browser_console returned 2 console message(s), 1 JS error(s)"
    assert wrapped["bounded_payload"] == {
        "success": True,
        "total_messages": 2,
        "total_errors": 1,
        "console_messages": [
            {"type": "log", "text": "x" * 512, "source": "console", "truncated": True},
            {"type": "error", "text": "short error", "source": "console"},
        ],
        "js_errors": [{"message": "boom", "source": "exception"}],
    }
    assert "x" * 1000 not in json.dumps(wrapped, ensure_ascii=False)


def test_browser_get_images_model_context_keeps_safe_url_references_only():
    from model_tools import _wrap_tool_result_for_model_context
    from tools import browser_tool  # noqa: F401 - ensure registry registration

    raw = json.dumps({
        "success": True,
        "images": [
            {"src": "https://example.com/a.png", "alt": "hero", "width": 640, "height": 480},
            {"src": "data:image/png;base64," + "A" * 120, "alt": "inline"},
            {"src": "https://user:pass@example.com/b.png", "alt": "userinfo"},
        ],
        "count": 3,
    })

    wrapped = json.loads(_wrap_tool_result_for_model_context("browser_get_images", raw))

    assert wrapped["tool_name"] == "browser_get_images"
    assert wrapped["tool_class"] == "browser"
    assert wrapped["summary"] == "browser_get_images returned 3 image reference(s)"
    assert wrapped["output_references"] == ["https://example.com/a.png"]
    assert wrapped["bounded_payload"] == {
        "success": True,
        "count": 3,
        "images": [
            {"src": "https://example.com/a.png", "alt": "hero", "width": 640, "height": 480},
            {"src": "[omitted unsafe image reference]", "alt": "inline"},
            {"src": "[omitted unsafe image reference]", "alt": "userinfo"},
        ],
    }
    dumped = json.dumps(wrapped, ensure_ascii=False)
    assert "data:image" not in dumped
    assert "user:pass" not in dumped
