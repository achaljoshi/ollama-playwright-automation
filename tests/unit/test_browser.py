"""Tests for page_signature helper (no live browser needed)."""

from oapw.core.browser import page_signature


def test_signature_stable():
    html = "<html><body><div id='app'><button>Click</button></div></body></html>"
    assert page_signature(html) == page_signature(html)


def test_signature_text_insensitive():
    """Same structure, different text → same signature."""
    a = "<html><body><p>Hello world</p></body></html>"
    b = "<html><body><p>Goodbye world</p></body></html>"
    assert page_signature(a) == page_signature(b)


def test_signature_structure_sensitive():
    """Different structure → different signature."""
    a = "<html><body><p>Hello</p></body></html>"
    b = "<html><body><div><p>Hello</p></div></body></html>"
    assert page_signature(a) != page_signature(b)


def test_signature_is_hex_string():
    sig = page_signature("<html></html>")
    assert isinstance(sig, str)
    assert len(sig) == 32  # blake2b digest_size=16 → 32 hex chars
    int(sig, 16)           # parseable as hex
