"""Tests for text variant generation in RoleTextStrategy (no browser needed)."""

from oapw.healing.strategies import _text_variants, RoleTextStrategy


class TestTextVariants:
    def test_produces_variants(self):
        variants = _text_variants("Sign in")
        assert len(variants) > 1

    def test_includes_original(self):
        variants = _text_variants("Submit")
        assert "Submit" in variants

    def test_synonym_expansion_login(self):
        variants = _text_variants("login")
        lower = [v.lower() for v in variants]
        assert any("sign in" in v for v in lower) or any("log in" in v for v in lower)

    def test_synonym_expansion_sign_in(self):
        variants = _text_variants("Sign in")
        lower = [v.lower() for v in variants]
        assert any("login" in v for v in lower)

    def test_empty_input(self):
        assert _text_variants("") == []

    def test_no_duplicates(self):
        variants = _text_variants("Submit")
        assert len(variants) == len(set(variants))

    def test_case_variants(self):
        variants = _text_variants("search")
        assert "SEARCH" in variants
        assert "Search" in variants
