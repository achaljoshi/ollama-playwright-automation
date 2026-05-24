"""Tests for Jinja2 prompt templates."""

import oapw.prompts as prompts


def test_locator_resolve_renders():
    out = prompts.render(
        "locator_resolve.j2",
        intent="the submit button",
        dom_context="[button] \"Submit\" id=submit-btn",
        aom_context="",
    )
    assert "submit button" in out
    assert "[button]" in out
    assert "JSON" in out


def test_locator_resolve_no_aom():
    out = prompts.render(
        "locator_resolve.j2",
        intent="email field",
        dom_context="[textbox] placeholder=\"Email\"",
        aom_context=None,
    )
    assert "email field" in out
    assert "Accessibility tree" not in out


def test_planner_renders():
    out = prompts.render(
        "planner.j2",
        goal="Log in with email user@example.com",
        url="https://example.com/login",
        dom_context="[textbox] \"Email\" id=email\n[button] \"Sign in\"",
    )
    assert "Log in with email" in out
    assert "https://example.com/login" in out
    assert "[textbox]" in out


def test_extract_renders():
    out = prompts.render(
        "extract.j2",
        query="Price of first product as a number",
        page_text="Nike Air Max ₹4,999 Add to cart",
    )
    assert "Price of first product" in out
    assert "₹4,999" in out


def test_assert_renders():
    out = prompts.render(
        "assert.j2",
        assertion="Cart shows 1 item",
        page_text="Your cart: 1 item",
        dom_context="",
    )
    assert "Cart shows 1 item" in out
    assert "Your cart: 1 item" in out
