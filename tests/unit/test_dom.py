"""Tests for DOM serializer (no live browser needed)."""

from oapw.core.dom import serialize_elements


def test_serialize_button():
    elements = [{"role": "button", "text": "Sign in", "id": "btn-signin"}]
    out = serialize_elements(elements)
    assert "[button]" in out
    assert '"Sign in"' in out
    assert "id=btn-signin" in out


def test_serialize_input_with_label_and_placeholder():
    elements = [{"role": "textbox", "label": "Email address", "placeholder": "Enter email", "name": "email"}]
    out = serialize_elements(elements)
    assert "[textbox]" in out
    assert '"Email address"' in out
    assert 'placeholder="Enter email"' in out


def test_serialize_link_with_href():
    elements = [{"role": "link", "text": "Forgot password?", "href": "/forgot"}]
    out = serialize_elements(elements)
    assert "[link]" in out
    assert '"Forgot password?"' in out
    assert 'href="/forgot"' in out


def test_serialize_disabled_required():
    elements = [{"role": "button", "text": "Submit", "disabled": True, "required": False}]
    out = serialize_elements(elements)
    assert "(disabled)" in out


def test_serialize_max_elements():
    elements = [{"role": "button", "text": f"Btn{i}"} for i in range(200)]
    out = serialize_elements(elements, max_elements=10)
    lines = out.strip().split("\n")
    assert len(lines) == 10


def test_serialize_empty():
    assert serialize_elements([]) == ""


def test_serialize_strips_null_fields():
    elements = [{"role": "button", "text": "OK", "id": None, "placeholder": None}]
    out = serialize_elements(elements)
    assert "id=" not in out
    assert "placeholder=" not in out
