"""Tests for AOM snapshot serializer (no live browser needed)."""

from oapw.core.aom import aom_snapshot_to_text


def test_basic_snapshot():
    snapshot = {
        "role": "WebArea",
        "name": "Login",
        "children": [
            {"role": "textbox", "name": "Email", "required": True},
            {"role": "textbox", "name": "Password"},
            {"role": "button", "name": "Sign in"},
        ],
    }
    text = aom_snapshot_to_text(snapshot)
    assert "textbox" in text
    assert '"Email"' in text
    assert "required" in text
    assert "button" in text
    assert '"Sign in"' in text


def test_none_snapshot():
    text = aom_snapshot_to_text(None)
    assert "no accessibility tree" in text


def test_nesting():
    snapshot = {
        "role": "dialog",
        "name": "Confirm",
        "children": [
            {"role": "button", "name": "OK"},
            {"role": "button", "name": "Cancel"},
        ],
    }
    text = aom_snapshot_to_text(snapshot)
    lines = text.split("\n")
    # dialog at root, buttons indented
    assert not lines[0].startswith(" ")
    assert lines[1].startswith("  ")


def test_max_lines():
    children = [{"role": "button", "name": f"Btn{i}"} for i in range(200)]
    snapshot = {"role": "WebArea", "name": "Page", "children": children}
    text = aom_snapshot_to_text(snapshot, max_lines=10)
    assert len(text.split("\n")) == 10


def test_checkbox_states():
    snapshot = {
        "role": "WebArea",
        "name": "",
        "children": [
            {"role": "checkbox", "name": "Remember me", "checked": True},
            {"role": "checkbox", "name": "Newsletter", "checked": False},
        ],
    }
    text = aom_snapshot_to_text(snapshot)
    assert "checked" in text
    assert "unchecked" in text
