"""A résumé's contact details: typed items, each drawn with its icon
(ADR 0048).

The model writes the contact line as free text, as a résumé has it; it is
read into items here, by rules, so the page can draw an icon beside each and
the user can change its kind. A link is shown as text and never fetched.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from advisor.resume.domain.constants import MAX_CONTACT, MAX_CONTACTS


class ContactKind(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    GITHUB = "github"
    LINKEDIN = "linkedin"
    WEBSITE = "website"
    LOCATION = "location"


@dataclass(frozen=True, slots=True)
class ContactItem:
    kind: ContactKind
    value: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": str(self.kind), "value": self.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ContactItem:
        return cls(ContactKind(data["kind"]), str(data.get("value", "")))


_SEPARATORS = re.compile(r"\s*(?:·|\||,|;|\n|•)\s*")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE = re.compile(r"^\+?[\d\s().\-]{7,}$")
_DOMAIN = re.compile(r"^(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?$", re.IGNORECASE)


def get_contact_kind(value: str) -> ContactKind:
    """What a piece of a contact line is, by its shape. Pure."""
    text = value.strip()
    lowered = text.lower()
    if _EMAIL.match(text.removeprefix("mailto:")):
        return ContactKind.EMAIL
    if "github.com" in lowered:
        return ContactKind.GITHUB
    if "linkedin.com" in lowered:
        return ContactKind.LINKEDIN
    if _PHONE.match(text) and sum(c.isdigit() for c in text) >= 7:
        return ContactKind.PHONE
    if _DOMAIN.match(text):
        return ContactKind.WEBSITE
    return ContactKind.LOCATION


def get_contact_items(line: str) -> tuple[ContactItem, ...]:
    """A free-text contact line as typed items, in its order: split on the
    separators résumés use, empty pieces dropped, cut to the limits. Pure."""
    pieces = [p.strip() for p in _SEPARATORS.split(line) if p.strip()]
    return tuple(
        ContactItem(get_contact_kind(piece), piece[:MAX_CONTACT]) for piece in pieces[:MAX_CONTACTS]
    )


class ContactError(ValueError):
    """Contact details that break the limits."""


def assert_contacts_valid(contacts: tuple[ContactItem, ...]) -> None:
    if len(contacts) > MAX_CONTACTS:
        raise ContactError(f"a résumé has at most {MAX_CONTACTS} contact details")
    for item in contacts:
        if not item.value.strip():
            raise ContactError("a contact detail is empty")
        if len(item.value) > MAX_CONTACT:
            raise ContactError(f"a contact detail has at most {MAX_CONTACT} characters")
