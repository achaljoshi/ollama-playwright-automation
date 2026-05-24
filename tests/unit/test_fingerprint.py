"""Tests for ElementFingerprint and similarity scoring."""

import pytest
from oapw.healing.fingerprint import (
    ElementFingerprint,
    fingerprint_from_element,
    fingerprint_similarity,
    find_best_match,
)


class TestElementFingerprint:
    def test_hash_stable(self):
        fp = ElementFingerprint(role="button", name="Sign in", text="Sign in")
        assert fp.hash() == fp.hash()

    def test_hash_sensitive(self):
        fp1 = ElementFingerprint(role="button", name="Sign in")
        fp2 = ElementFingerprint(role="button", name="Login")
        assert fp1.hash() != fp2.hash()

    def test_roundtrip(self):
        fp = ElementFingerprint(role="textbox", label="Email", placeholder="Enter email")
        restored = ElementFingerprint.from_dict(fp.to_dict())
        assert restored.role == "textbox"
        assert restored.label == "Email"
        assert restored.placeholder == "Enter email"

    def test_from_dict_ignores_extra_keys(self):
        data = {"role": "button", "name": "OK", "unknown_key": "ignored"}
        fp = ElementFingerprint.from_dict(data)
        assert fp.role == "button"


class TestFingerprintSimilarity:
    def test_identical(self):
        fp = ElementFingerprint(role="button", name="Sign in", text="Sign in")
        assert fingerprint_similarity(fp, fp) == 1.0

    def test_exact_role_and_name_match(self):
        fp1 = ElementFingerprint(role="button", name="Sign in")
        fp2 = ElementFingerprint(role="button", name="Sign in")
        assert fingerprint_similarity(fp1, fp2) > 0.8

    def test_same_role_different_text(self):
        fp1 = ElementFingerprint(role="button", name="Sign in")
        fp2 = ElementFingerprint(role="button", name="Login")
        score = fingerprint_similarity(fp1, fp2)
        # role matches (weight 3.0) but name doesn't (weight 2.5) → ~3/5.5 ≈ 0.55
        # should be clearly lower than an exact match (1.0) but not near zero
        assert 0.4 < score < 0.7

    def test_completely_different(self):
        fp1 = ElementFingerprint(role="button", name="Sign in")
        fp2 = ElementFingerprint(role="textbox", name="Email address", placeholder="Enter email")
        score = fingerprint_similarity(fp1, fp2)
        assert score < 0.3

    def test_partial_text_match(self):
        fp1 = ElementFingerprint(role="button", name="Sign in")
        fp2 = ElementFingerprint(role="button", name="sign in here")
        score = fingerprint_similarity(fp1, fp2)
        assert score > 0.5

    def test_score_range(self):
        fp1 = ElementFingerprint(role="button", name="A")
        fp2 = ElementFingerprint(role="link", name="B")
        score = fingerprint_similarity(fp1, fp2)
        assert 0.0 <= score <= 1.0


class TestFingerprintFromElement:
    def test_button(self):
        el = {"role": "button", "text": "Sign in", "id": "btn", "tag": "button"}
        fp = fingerprint_from_element(el)
        assert fp.role == "button"
        assert fp.text == "Sign in"

    def test_input_with_label(self):
        el = {"role": "textbox", "label": "Email", "placeholder": "Enter email", "type": "email", "tag": "input"}
        fp = fingerprint_from_element(el)
        assert fp.label == "Email"
        assert fp.placeholder == "Enter email"
        assert fp.input_type == "email"

    def test_link_strips_domain(self):
        el = {"role": "link", "text": "Forgot?", "href": "https://example.com/forgot", "tag": "a"}
        fp = fingerprint_from_element(el)
        assert "example.com" not in fp.href
        assert "/forgot" in fp.href

    def test_stable_classes_filter_hashes(self):
        el = {"role": "button", "text": "OK", "class": "btn a3f7e21 btn-primary x1", "tag": "button"}
        fp = fingerprint_from_element(el)
        assert "a3f7e21" not in fp.stable_classes
        assert "btn" in fp.stable_classes


class TestFindBestMatch:
    def test_finds_match(self):
        candidates = [
            {"role": "button", "text": "Login", "tag": "button"},
            {"role": "textbox", "label": "Email", "tag": "input"},
        ]
        target = ElementFingerprint(role="button", name="Sign in", text="Sign in")
        result = find_best_match(target, candidates, threshold=0.2)
        assert result is not None
        el, score = result
        assert el["role"] == "button"

    def test_returns_none_below_threshold(self):
        candidates = [{"role": "textbox", "label": "Email", "tag": "input"}]
        target = ElementFingerprint(role="button", name="Sign in")
        result = find_best_match(target, candidates, threshold=0.9)
        assert result is None

    def test_empty_candidates(self):
        fp = ElementFingerprint(role="button", name="OK")
        assert find_best_match(fp, [], threshold=0.1) is None
