"""Common Pydantic data models and their factories for typical web app tests.

Ready-to-use factories covering the most common test data needs:
  - UserData / UserFactory
  - LoginCredentials / LoginCredentialsFactory
  - AddressData / AddressFactory
  - CreditCardData / CreditCardFactory (fake numbers only — passes Luhn)
  - ProductData / ProductFactory

Usage:
    user = UserFactory.build()
    creds = LoginCredentialsFactory.build(email="fixed@example.com")
    users = UserFactory.build_batch(5, role="admin")
    payload = UserFactory.build_dict()    # plain dict for API calls
"""

from __future__ import annotations

import random
from typing import Literal

from pydantic import BaseModel, Field

from oapw.factories.base import BaseFactory


# ── User ──────────────────────────────────────────────────────────────────────

class UserData(BaseModel):
    """Represents a user account for test purposes."""
    email: str
    username: str
    first_name: str
    last_name: str
    password: str
    role: Literal["admin", "viewer", "editor", "owner"] = "viewer"
    phone: str = ""
    is_active: bool = True


class UserFactory(BaseFactory):
    """Generate realistic UserData instances with unique emails."""
    model = UserData
    _defaults = {"role": "viewer", "is_active": True}


# ── Login credentials ─────────────────────────────────────────────────────────

class LoginCredentials(BaseModel):
    """Minimal credentials for form fill / API login."""
    email: str
    password: str


class LoginCredentialsFactory(BaseFactory):
    """Generate login credential pairs."""
    model = LoginCredentials


# ── Address ───────────────────────────────────────────────────────────────────

class AddressData(BaseModel):
    """Postal address for shipping / billing form tests."""
    street: str
    city: str
    state: str
    zip: str
    country: str = "US"


class AddressFactory(BaseFactory):
    """Generate realistic AddressData instances."""
    model = AddressData
    _defaults = {"country": "US"}


# ── Credit card ───────────────────────────────────────────────────────────────

def _luhn_checksum(number: str) -> int:
    """Compute Luhn check digit so fake card numbers pass format validation."""
    digits = [int(d) for d in number]
    digits.reverse()
    total = 0
    for i, d in enumerate(digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - (total % 10)) % 10


def _fake_card_number(prefix: str = "4", length: int = 16) -> str:
    """Generate a fake credit card number that passes Luhn validation."""
    partial = prefix + "".join(random.choices("0123456789", k=length - len(prefix) - 1))
    check = _luhn_checksum(partial + "0")
    return partial + str(check)


class CreditCardData(BaseModel):
    """Fake credit card for payment form tests. Numbers pass Luhn, not real cards."""
    number: str = Field(description="16-digit card number (Luhn-valid, fake)")
    expiry_month: str = Field(description="MM format, e.g. '12'")
    expiry_year: str = Field(description="YYYY format, e.g. '2027'")
    cvv: str = Field(description="3-digit CVV")
    holder_name: str


class CreditCardFactory(BaseFactory):
    """Generate fake (but Luhn-valid) credit card data for payment form tests."""
    model = CreditCardData

    @classmethod
    def _build_data(cls, seq: int, overrides: dict) -> dict:
        data = super()._build_data(seq, overrides)
        if "number" not in overrides:
            data["number"] = _fake_card_number()
        if "expiry_month" not in overrides:
            data["expiry_month"] = f"{random.randint(1, 12):02d}"
        if "expiry_year" not in overrides:
            data["expiry_year"] = str(2026 + (seq % 5))
        if "cvv" not in overrides:
            data["cvv"] = f"{random.randint(100, 999)}"
        if "holder_name" not in overrides:
            data["holder_name"] = f"Test User {seq}"
        return data


# ── Product ───────────────────────────────────────────────────────────────────

class ProductData(BaseModel):
    """A product or item for e-commerce / catalogue tests."""
    name: str
    slug: str
    description: str
    price: float
    sku: str
    stock: int = 100
    is_active: bool = True
    category: str = "general"


class ProductFactory(BaseFactory):
    """Generate ProductData instances with unique slugs and realistic prices."""
    model = ProductData
    _defaults = {"stock": 100, "is_active": True, "category": "general"}

    @classmethod
    def _build_data(cls, seq: int, overrides: dict) -> dict:
        data = super()._build_data(seq, overrides)
        if "price" not in overrides:
            data["price"] = round(random.uniform(1.99, 999.99), 2)
        if "sku" not in overrides:
            data["sku"] = f"SKU-{seq:06d}"
        return data


# ── Registry ──────────────────────────────────────────────────────────────────

class FactoryRegistry:
    """Named factory lookup — useful for fixtures.

    Usage:
        registry = FactoryRegistry()
        user = registry.build("user")
        creds = registry.build("credentials", email="fixed@example.com")
    """

    _factories: dict[str, type[BaseFactory]] = {
        "user": UserFactory,
        "credentials": LoginCredentialsFactory,
        "login": LoginCredentialsFactory,
        "address": AddressFactory,
        "card": CreditCardFactory,
        "credit_card": CreditCardFactory,
        "product": ProductFactory,
    }

    def register(self, name: str, factory: type[BaseFactory]) -> None:
        """Register a custom factory under ``name``."""
        self._factories[name] = factory

    def build(self, name: str, **overrides) -> BaseModel:
        """Build one instance from the factory registered as ``name``."""
        factory = self._factories.get(name)
        if not factory:
            raise KeyError(f"No factory registered as '{name}'. "
                           f"Available: {sorted(self._factories)}")
        return factory.build(**overrides)

    def build_batch(self, name: str, count: int, **overrides) -> list[BaseModel]:
        factory = self._factories.get(name)
        if not factory:
            raise KeyError(f"No factory registered as '{name}'.")
        return factory.build_batch(count, **overrides)

    def build_dict(self, name: str, **overrides) -> dict:
        return self.build(name, **overrides).model_dump()
