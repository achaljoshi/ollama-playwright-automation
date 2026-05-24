"""Tests for the PII masking module."""

from __future__ import annotations

import pytest

from oapw.security.pii import PiiMasker, get_pii_masker


@pytest.fixture
def masker() -> PiiMasker:
    return PiiMasker()


# ── Email masking ─────────────────────────────────────────────────────────────

class TestEmailMasking:
    def test_masks_simple_email(self, masker):
        assert "[EMAIL]" in masker.mask("Contact alice@example.com")

    def test_masks_subdomain_email(self, masker):
        assert "[EMAIL]" in masker.mask("user@mail.company.co.uk")

    def test_masks_plus_addressed_email(self, masker):
        assert "[EMAIL]" in masker.mask("user+tag@example.com")

    def test_masks_multiple_emails(self, masker):
        result = masker.mask("From alice@a.com to bob@b.com")
        assert result.count("[EMAIL]") == 2

    def test_no_false_positive_on_clean_text(self, masker):
        result = masker.mask("Hello World, no PII here")
        assert result == "Hello World, no PII here"


# ── Phone masking ─────────────────────────────────────────────────────────────

class TestPhoneMasking:
    def test_masks_us_phone_dashes(self, masker):
        assert "[PHONE]" in masker.mask("Call 555-123-4567 now")

    def test_masks_us_phone_dots(self, masker):
        assert "[PHONE]" in masker.mask("Call 555.123.4567 now")

    def test_masks_us_phone_spaces(self, masker):
        assert "[PHONE]" in masker.mask("Reach us at 555 123 4567")

    def test_masks_international_phone(self, masker):
        assert "[PHONE]" in masker.mask("Call +1 555-123-4567")

    def test_masks_parenthesized_area_code(self, masker):
        assert "[PHONE]" in masker.mask("(555) 123-4567")


# ── Credit card masking ───────────────────────────────────────────────────────

class TestCardMasking:
    def test_masks_visa_number(self, masker):
        assert "[CARD]" in masker.mask("Card: 4111111111111111")

    def test_masks_card_with_dashes(self, masker):
        assert "[CARD]" in masker.mask("Card: 4111-1111-1111-1111")

    def test_masks_card_with_spaces(self, masker):
        assert "[CARD]" in masker.mask("Card: 4111 1111 1111 1111")

    def test_does_not_mask_short_numbers(self, masker):
        # 4-digit number should not be masked as card
        result = masker.mask("Pin: 1234")
        assert "[CARD]" not in result


# ── SSN masking ───────────────────────────────────────────────────────────────

class TestSSNMasking:
    def test_masks_ssn(self, masker):
        assert "[SSN]" in masker.mask("SSN: 123-45-6789")

    def test_does_not_mask_000_ssn(self, masker):
        # All-zero prefix is invalid SSN
        result = masker.mask("000-45-6789")
        assert "[SSN]" not in result


# ── JWT masking ───────────────────────────────────────────────────────────────

class TestJWTMasking:
    def test_masks_jwt_token(self, masker):
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiJ1c2VyMTIzIiwibmFtZSI6IkFsaWNlIn0"
            ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        result = masker.mask(f"token={jwt}")
        assert "[JWT]" in result

    def test_masks_bearer_token(self, masker):
        result = masker.mask("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def")
        assert "[TOKEN]" in result or "[JWT]" in result


# ── AWS key masking ───────────────────────────────────────────────────────────

class TestAWSKeyMasking:
    def test_masks_aws_access_key(self, masker):
        result = masker.mask("Key: AKIAIOSFODNN7EXAMPLE")
        assert "[AWS_KEY]" in result

    def test_does_not_mask_random_uppercase_string(self, masker):
        result = masker.mask("Value: HELLO_WORLD_TEST_HERE")
        # Should not match AKIA pattern
        assert "[AWS_KEY]" not in result


# ── Password in JSON / form masking ──────────────────────────────────────────

class TestPasswordMasking:
    def test_masks_json_password(self, masker):
        result = masker.mask('{"email": "u@t.com", "password": "Secret123!"}')
        assert "[REDACTED]" in result
        assert "Secret123!" not in result

    def test_masks_json_secret(self, masker):
        result = masker.mask('{"api_key": "my-secret-key-12345"}')
        assert "[REDACTED]" in result

    def test_preserves_email_in_same_string(self, masker):
        result = masker.mask('{"email": "u@t.com", "password": "pass123"}')
        assert "[EMAIL]" in result
        assert "[REDACTED]" in result
        assert "pass123" not in result

    def test_case_insensitive_password_key(self, masker):
        result = masker.mask('PASSWORD="supersecret"')
        assert "[REDACTED]" in result


# ── mask_dict ─────────────────────────────────────────────────────────────────

class TestMaskDict:
    def test_masks_string_values(self, masker):
        d = {"email": "alice@example.com", "name": "Alice"}
        result = masker.mask_dict(d)
        assert result["email"] == "[EMAIL]"
        assert result["name"] == "Alice"

    def test_leaves_non_string_values(self, masker):
        d = {"count": 42, "active": True}
        result = masker.mask_dict(d)
        assert result == {"count": 42, "active": True}

    def test_masks_nested_dict(self, masker):
        d = {"user": {"email": "u@t.com", "role": "admin"}}
        result = masker.mask_dict(d)
        assert result["user"]["email"] == "[EMAIL]"
        assert result["user"]["role"] == "admin"

    def test_masks_list_of_strings(self, masker):
        d = {"emails": ["a@b.com", "c@d.com"]}
        result = masker.mask_dict(d)
        assert result["emails"] == ["[EMAIL]", "[EMAIL]"]

    def test_handles_none_values(self, masker):
        d = {"field": None}
        result = masker.mask_dict(d)
        assert result["field"] is None

    def test_handles_empty_dict(self, masker):
        assert masker.mask_dict({}) == {}


# ── mask_json ─────────────────────────────────────────────────────────────────

class TestMaskJson:
    def test_parses_and_masks_json(self, masker):
        json_str = '{"email": "u@t.com", "count": 1}'
        result = masker.mask_json(json_str)
        assert "[EMAIL]" in result
        assert "u@t.com" not in result

    def test_falls_back_on_invalid_json(self, masker):
        result = masker.mask_json("not json but has alice@example.com in it")
        assert "[EMAIL]" in result


# ── detect ────────────────────────────────────────────────────────────────────

class TestDetect:
    def test_detects_email(self, masker):
        findings = masker.detect("Email: user@example.com")
        types = [f.type for f in findings]
        assert "EMAIL" in types

    def test_detect_returns_correct_position(self, masker):
        text = "Hi user@example.com!"
        findings = masker.detect(text)
        email_findings = [f for f in findings if f.type == "EMAIL"]
        assert email_findings
        found = email_findings[0]
        assert text[found.start:found.end] == "user@example.com"

    def test_detect_empty_string_returns_empty(self, masker):
        assert masker.detect("") == []

    def test_detect_clean_text_returns_empty(self, masker):
        assert masker.detect("Hello World nothing sensitive here") == []


# ── has_pii ───────────────────────────────────────────────────────────────────

class TestHasPii:
    def test_true_for_email(self, masker):
        assert masker.has_pii("user@example.com")

    def test_false_for_clean_text(self, masker):
        assert not masker.has_pii("Hello World")


# ── Singleton ─────────────────────────────────────────────────────────────────

def test_get_pii_masker_returns_same_instance():
    m1 = get_pii_masker()
    m2 = get_pii_masker()
    assert m1 is m2


def test_masker_mask_empty_string():
    masker = PiiMasker()
    assert masker.mask("") == ""


def test_masker_mask_none_like_empty():
    masker = PiiMasker()
    # None is not passed as str, but empty string handled
    assert masker.mask("") == ""
