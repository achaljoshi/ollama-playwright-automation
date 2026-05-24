"""Tests for the test data factory framework."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from oapw.factories.base import BaseFactory, _generate_for_field
from oapw.factories.common import (
    AddressData,
    AddressFactory,
    CreditCardData,
    CreditCardFactory,
    FactoryRegistry,
    LoginCredentials,
    LoginCredentialsFactory,
    ProductData,
    ProductFactory,
    UserData,
    UserFactory,
    _luhn_checksum,
)


# ── BaseFactory ───────────────────────────────────────────────────────────────

class SimpleModel(BaseModel):
    name: str
    email: str
    age: int
    active: bool


class SimpleFactory(BaseFactory):
    model = SimpleModel


class TestBaseFactory:
    def setup_method(self):
        SimpleFactory.reset_sequence()

    def test_build_returns_model_instance(self):
        obj = SimpleFactory.build()
        assert isinstance(obj, SimpleModel)

    def test_build_overrides_apply(self):
        obj = SimpleFactory.build(name="Fixed Name", age=42)
        assert obj.name == "Fixed Name"
        assert obj.age == 42

    def test_build_generates_email_like_value(self):
        obj = SimpleFactory.build()
        assert "@" in obj.email

    def test_build_generates_bool_value(self):
        obj = SimpleFactory.build()
        assert isinstance(obj.active, bool)

    def test_build_generates_int_value(self):
        obj = SimpleFactory.build()
        assert isinstance(obj.age, int)

    def test_build_batch_returns_correct_count(self):
        objs = SimpleFactory.build_batch(5)
        assert len(objs) == 5

    def test_build_batch_all_instances_correct_type(self):
        objs = SimpleFactory.build_batch(3)
        assert all(isinstance(o, SimpleModel) for o in objs)

    def test_build_batch_emails_are_unique(self):
        objs = SimpleFactory.build_batch(10)
        emails = [o.email for o in objs]
        assert len(set(emails)) == len(emails)

    def test_build_dict_returns_dict(self):
        d = SimpleFactory.build_dict()
        assert isinstance(d, dict)
        assert "email" in d

    def test_reset_sequence_restarts_counter(self):
        obj1 = SimpleFactory.build()
        SimpleFactory.reset_sequence()
        obj3 = SimpleFactory.build()
        # After reset, seq=1 again — local parts of emails match (domain may differ)
        local1 = obj1.email.split("@")[0]
        local3 = obj3.email.split("@")[0]
        assert local1 == local3

    def test_sequence_increments_per_call(self):
        SimpleFactory.reset_sequence()
        objs = SimpleFactory.build_batch(3)
        # Each sequence is unique
        emails = {o.email for o in objs}
        assert len(emails) == 3


# ── _generate_for_field heuristics ───────────────────────────────────────────

class TestFieldHeuristics:
    def test_email_field_contains_at(self):
        val = _generate_for_field("email", str, 1)
        assert "@" in val

    def test_username_field_generates_string(self):
        val = _generate_for_field("username", str, 1)
        assert isinstance(val, str)
        assert len(val) > 0

    def test_password_field_generates_string(self):
        val = _generate_for_field("password", str, 1)
        assert isinstance(val, str)
        assert len(val) >= 8

    def test_phone_field_starts_with_plus_or_digit(self):
        val = _generate_for_field("phone", str, 1)
        assert val[0] in ("+", "1", "2", "3", "4", "5", "6", "7", "8", "9")

    def test_url_field_starts_with_https(self):
        val = _generate_for_field("url", str, 1)
        assert val.startswith("https://")

    def test_id_field_generates_uuid(self):
        val = _generate_for_field("user_id", str, 1)
        assert len(val) == 36  # UUID with hyphens

    def test_int_annotation_generates_int(self):
        val = _generate_for_field("count", int, 5)
        assert val == 5

    def test_bool_annotation_generates_bool(self):
        val = _generate_for_field("is_active", bool, 1)
        assert isinstance(val, bool)

    def test_unknown_str_field_uses_fieldname(self):
        # "widget_type" doesn't match any specific heuristic keyword except "type" → "default"
        # Use a field with no known heuristic keyword to get the fieldname fallback
        val = _generate_for_field("frob_quux", str, 3)
        assert "frob_quux" in val


# ── UserFactory ───────────────────────────────────────────────────────────────

class TestUserFactory:
    def setup_method(self):
        UserFactory.reset_sequence()

    def test_build_returns_user_data(self):
        user = UserFactory.build()
        assert isinstance(user, UserData)

    def test_email_is_valid_format(self):
        user = UserFactory.build()
        assert "@" in user.email
        assert "." in user.email.split("@")[1]

    def test_default_role_is_viewer(self):
        user = UserFactory.build()
        assert user.role == "viewer"

    def test_override_role(self):
        admin = UserFactory.build(role="admin")
        assert admin.role == "admin"

    def test_is_active_default_true(self):
        user = UserFactory.build()
        assert user.is_active is True

    def test_batch_emails_unique(self):
        users = UserFactory.build_batch(20)
        emails = [u.email for u in users]
        assert len(set(emails)) == 20


# ── LoginCredentialsFactory ───────────────────────────────────────────────────

class TestLoginCredentialsFactory:
    def setup_method(self):
        LoginCredentialsFactory.reset_sequence()

    def test_build_returns_credentials(self):
        creds = LoginCredentialsFactory.build()
        assert isinstance(creds, LoginCredentials)
        assert creds.email
        assert creds.password

    def test_fixed_email_override(self):
        creds = LoginCredentialsFactory.build(email="fixed@test.com")
        assert creds.email == "fixed@test.com"


# ── AddressFactory ────────────────────────────────────────────────────────────

class TestAddressFactory:
    def setup_method(self):
        AddressFactory.reset_sequence()

    def test_build_returns_address(self):
        addr = AddressFactory.build()
        assert isinstance(addr, AddressData)

    def test_default_country_is_us(self):
        addr = AddressFactory.build()
        assert addr.country == "US"

    def test_zip_is_5_digits(self):
        addr = AddressFactory.build()
        assert addr.zip.isdigit()
        assert len(addr.zip) == 5


# ── CreditCardFactory ─────────────────────────────────────────────────────────

class TestCreditCardFactory:
    def setup_method(self):
        CreditCardFactory.reset_sequence()

    def test_build_returns_credit_card(self):
        card = CreditCardFactory.build()
        assert isinstance(card, CreditCardData)

    def test_card_number_is_16_digits(self):
        card = CreditCardFactory.build()
        digits = card.number.replace("-", "").replace(" ", "")
        assert len(digits) == 16
        assert digits.isdigit()

    def test_card_passes_luhn(self):
        """Verifies _luhn_checksum produces valid cards."""
        CreditCardFactory.reset_sequence()
        for _ in range(5):
            card = CreditCardFactory.build()
            digits = [int(d) for d in card.number]
            # Standard Luhn check
            total = 0
            for i, d in enumerate(reversed(digits)):
                if i % 2 == 1:
                    d *= 2
                    if d > 9:
                        d -= 9
                total += d
            assert total % 10 == 0, f"Card {card.number} failed Luhn check"

    def test_expiry_month_is_two_digits(self):
        card = CreditCardFactory.build()
        assert card.expiry_month.isdigit()
        assert 1 <= int(card.expiry_month) <= 12

    def test_cvv_is_three_digits(self):
        card = CreditCardFactory.build()
        assert len(card.cvv) == 3
        assert card.cvv.isdigit()


# ── ProductFactory ────────────────────────────────────────────────────────────

class TestProductFactory:
    def setup_method(self):
        ProductFactory.reset_sequence()

    def test_build_returns_product(self):
        p = ProductFactory.build()
        assert isinstance(p, ProductData)

    def test_price_is_positive_float(self):
        p = ProductFactory.build()
        assert p.price > 0

    def test_sku_format(self):
        p = ProductFactory.build()
        assert p.sku.startswith("SKU-")

    def test_default_stock(self):
        p = ProductFactory.build()
        assert p.stock == 100

    def test_batch_skus_unique(self):
        products = ProductFactory.build_batch(5)
        skus = [p.sku for p in products]
        assert len(set(skus)) == 5


# ── FactoryRegistry ───────────────────────────────────────────────────────────

class TestFactoryRegistry:
    def setup_method(self):
        for cls in [UserFactory, LoginCredentialsFactory, AddressFactory,
                    CreditCardFactory, ProductFactory]:
            cls.reset_sequence()

    def test_build_user(self):
        reg = FactoryRegistry()
        user = reg.build("user")
        assert isinstance(user, UserData)

    def test_build_credentials(self):
        reg = FactoryRegistry()
        creds = reg.build("credentials")
        assert isinstance(creds, LoginCredentials)

    def test_build_login_alias(self):
        reg = FactoryRegistry()
        creds = reg.build("login")
        assert isinstance(creds, LoginCredentials)

    def test_build_address(self):
        reg = FactoryRegistry()
        addr = reg.build("address")
        assert isinstance(addr, AddressData)

    def test_build_card(self):
        reg = FactoryRegistry()
        card = reg.build("card")
        assert isinstance(card, CreditCardData)

    def test_build_product(self):
        reg = FactoryRegistry()
        prod = reg.build("product")
        assert isinstance(prod, ProductData)

    def test_build_with_override(self):
        reg = FactoryRegistry()
        user = reg.build("user", role="admin")
        assert user.role == "admin"

    def test_build_dict_returns_dict(self):
        reg = FactoryRegistry()
        d = reg.build_dict("user")
        assert isinstance(d, dict)
        assert "email" in d

    def test_unknown_name_raises_key_error(self):
        reg = FactoryRegistry()
        with pytest.raises(KeyError, match="No factory registered"):
            reg.build("unknown_factory_xyz")

    def test_register_custom_factory(self):
        class MyModel(BaseModel):
            code: str

        class MyFactory(BaseFactory):
            model = MyModel

        reg = FactoryRegistry()
        reg.register("my_model", MyFactory)
        obj = reg.build("my_model")
        assert isinstance(obj, MyModel)

    def test_build_batch(self):
        reg = FactoryRegistry()
        users = reg.build_batch("user", 3)
        assert len(users) == 3
        assert all(isinstance(u, UserData) for u in users)
