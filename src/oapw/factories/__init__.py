"""Test data factories — generate realistic fake data for web app tests."""

from oapw.factories.base import BaseFactory
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
)

__all__ = [
    "BaseFactory",
    "FactoryRegistry",
    "UserData",
    "UserFactory",
    "LoginCredentials",
    "LoginCredentialsFactory",
    "AddressData",
    "AddressFactory",
    "CreditCardData",
    "CreditCardFactory",
    "ProductData",
    "ProductFactory",
]
