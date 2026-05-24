"""BaseFactory — zero-dependency Pydantic-model test data factory.

Generates realistic fake values from field name heuristics, with full
override support and sequence-based uniqueness.

Design goals:
  - Zero extra dependencies (no faker, polyfactory, or factory_boy required)
  - Fields auto-generated from name heuristics (email → email-like string)
  - Per-factory sequence counter for unique values across batch builds
  - Easy subclassing — just set ``model`` and optionally override ``_defaults``

Usage:
    class UserFactory(BaseFactory):
        model = UserData
        _defaults = {"role": "viewer"}   # optional class-level defaults

    user = UserFactory.build()                      # auto-generated
    admin = UserFactory.build(role="admin")         # override one field
    users = UserFactory.build_batch(10)             # 10 unique users
    raw = UserFactory.build_dict(email="x@y.com")  # dict instead of model
"""

from __future__ import annotations

import random
import string
import uuid
from typing import Any, ClassVar

from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic._internal._fields import PydanticMetadata  # noqa: F401 (unused but imported for compat)

try:
    from pydantic_core import PydanticUndefined
except ImportError:
    PydanticUndefined = None  # type: ignore[assignment]

# ── Default value generators by field name keyword ────────────────────────────

_ADJECTIVES = ["swift", "bright", "calm", "bold", "wise", "fair", "keen", "glad"]
_NOUNS = ["tiger", "river", "stone", "cloud", "flame", "grove", "field", "bridge"]
_DOMAINS = ["example.com", "test.io", "testmail.dev", "mailtest.org"]
_TLDS = ["com", "io", "org", "net"]
_FIRST_NAMES = ["Alice", "Bob", "Carol", "David", "Eva", "Frank", "Grace", "Henry"]
_LAST_NAMES = ["Smith", "Jones", "Taylor", "Brown", "Wilson", "Davis", "Evans", "Green"]
_STREETS = ["Main St", "Oak Ave", "Park Blvd", "Elm St", "Cedar Rd", "Maple Dr"]
_CITIES = ["Springfield", "Shelbyville", "Capital City", "Oakdale", "Rivertown"]
_STATES = ["CA", "NY", "TX", "WA", "FL", "OR", "CO", "IL"]


def _rand_word() -> str:
    return random.choice(_ADJECTIVES) + random.choice(_NOUNS)


def _generate_for_field(field_name: str, annotation: Any, seq: int) -> Any:
    """Return a realistic fake value for ``field_name`` at sequence ``seq``."""
    name = field_name.lower()

    # ── String heuristics by field name ──────────────────────────────────────
    if "email" in name:
        return f"user{seq}@{random.choice(_DOMAINS)}"
    if "username" in name or name == "user":
        adj = random.choice(_ADJECTIVES)
        return f"{adj}_user_{seq}"
    if "first_name" in name or name == "firstname":
        return _FIRST_NAMES[(seq - 1) % len(_FIRST_NAMES)]
    if "last_name" in name or name == "lastname" or name == "surname":
        return _LAST_NAMES[(seq - 1) % len(_LAST_NAMES)]
    if name in ("name", "full_name", "fullname", "display_name"):
        return f"{_FIRST_NAMES[(seq-1) % len(_FIRST_NAMES)]} {_LAST_NAMES[(seq-1) % len(_LAST_NAMES)]}"
    if "password" in name or "passwd" in name or "pwd" in name:
        return f"Secure{seq}!Pass"
    if "phone" in name or "mobile" in name or "tel" in name:
        return f"+1555{seq:07d}"
    if "zip" in name or "postal" in name or "postcode" in name:
        return f"{10000 + seq:05d}"
    if "address" in name or "street" in name:
        return f"{seq} {random.choice(_STREETS)}"
    if "city" in name or "town" in name:
        return _CITIES[(seq - 1) % len(_CITIES)]
    if "state" in name or "region" in name or "province" in name:
        return _STATES[(seq - 1) % len(_STATES)]
    if "country" in name:
        return "US"
    if "url" in name or "link" in name or "website" in name:
        return f"https://example{seq}.com"
    if "image" in name or "avatar" in name or "photo" in name:
        return f"https://example.com/images/{seq}.jpg"
    if "description" in name or "bio" in name or "note" in name or "comment" in name:
        return f"Auto-generated description {seq}"
    if "title" in name or "label" in name or "subject" in name:
        return f"Title {seq}"
    if "slug" in name or "handle" in name:
        return f"item-{seq}"
    if "token" in name or "secret" in name or "key" in name or "api_key" in name:
        return uuid.uuid4().hex
    if "uuid" in name or name == "id" or name.endswith("_id"):
        return str(uuid.uuid4())
    if "color" in name or "colour" in name:
        return f"#{random.randint(0, 0xFFFFFF):06X}"
    if "role" in name or "type" in name or "kind" in name or "category" in name:
        return "default"
    if "status" in name:
        return "active"

    # ── Type-based fallback ───────────────────────────────────────────────────
    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", ())

    # Optional[X] → unwrap X
    if origin is type(None):
        return None
    if origin is not None and hasattr(annotation, "__args__"):
        # Optional[X] is Union[X, None]
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _generate_for_field(field_name, non_none[0], seq)

    if annotation is int or annotation == "int":
        return seq
    if annotation is float or annotation == "float":
        return float(seq)
    if annotation is bool or annotation == "bool":
        return True
    if annotation is str or annotation == "str":
        return f"{field_name}_{seq}"
    if annotation is list or (origin is list):
        return []
    if annotation is dict or (origin is dict):
        return {}

    return None


class BaseFactory:
    """Generate Pydantic model instances filled with realistic fake data.

    Subclass and set ``model`` to a Pydantic ``BaseModel`` subclass.
    Optionally set ``_defaults`` for class-level field overrides.

    Example::

        class UserFactory(BaseFactory):
            model = UserData
            _defaults = {"role": "viewer"}

        user = UserFactory.build()
        admin = UserFactory.build(role="admin")
        users = UserFactory.build_batch(5)
    """

    model: ClassVar[type[BaseModel]]
    _defaults: ClassVar[dict[str, Any]] = {}
    _seq: ClassVar[int] = 0

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._seq = 0  # each subclass gets its own counter

    @classmethod
    def _next_seq(cls) -> int:
        cls._seq += 1
        return cls._seq

    @classmethod
    def _build_data(cls, seq: int, overrides: dict[str, Any]) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for field_name, field_info in cls.model.model_fields.items():
            if field_name in overrides:
                data[field_name] = overrides[field_name]
            elif field_name in cls._defaults:
                data[field_name] = cls._defaults[field_name]
            elif (
                field_info.default is not None
                and field_info.default is not PydanticUndefined
            ):
                data[field_name] = field_info.default
            elif field_info.default_factory is not None:  # type: ignore[misc]
                data[field_name] = field_info.default_factory()
            else:
                data[field_name] = _generate_for_field(
                    field_name, field_info.annotation, seq
                )
        return data

    @classmethod
    def build(cls, **overrides: Any) -> BaseModel:
        """Build a single model instance with optional field overrides."""
        seq = cls._next_seq()
        return cls.model(**cls._build_data(seq, overrides))

    @classmethod
    def build_batch(cls, count: int, **overrides: Any) -> list[BaseModel]:
        """Build ``count`` model instances. Each gets a unique sequence number."""
        return [cls.build(**overrides) for _ in range(count)]

    @classmethod
    def build_dict(cls, **overrides: Any) -> dict[str, Any]:
        """Build a model instance and return it as a plain dict."""
        return cls.build(**overrides).model_dump()

    @classmethod
    def reset_sequence(cls) -> None:
        """Reset the sequence counter to 0 (useful in test setUp)."""
        cls._seq = 0
