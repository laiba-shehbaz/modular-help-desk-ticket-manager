"""Input validation. Pure functions: take raw text, return a clean value or raise ValidationError."""
from __future__ import annotations

from .errors import ValidationError
from .models import Priority, Status

NAME_EXTRA_CHARACTERS = " .'-"


def _clean(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def validate_customer_name(value) -> str:
    text = _clean(value)
    if not text:
        raise ValidationError("Customer name cannot be empty.")
    if not 2 <= len(text) <= 60:
        raise ValidationError("Customer name must be between 2 and 60 characters.")
    if not text[0].isalpha() or any(not (c.isalpha() or c in NAME_EXTRA_CHARACTERS) for c in text):
        raise ValidationError("Customer name may contain only letters, spaces, dots, apostrophes and hyphens.")
    return text


def validate_issue(value) -> str:
    text = _clean(value)
    if not text:
        raise ValidationError("Issue description cannot be empty.")
    if not 5 <= len(text) <= 500:
        raise ValidationError(f"Issue description must be 5 to 500 characters (you typed {len(text)}).")
    return text


def validate_resolution(value) -> str | None:
    text = _clean(value)
    if not text:
        return None
    if len(text) > 300:
        raise ValidationError("Resolution note must be 300 characters or fewer.")
    return text


def validate_keyword(value) -> str:
    text = _clean(value)
    if not 2 <= len(text) <= 50:
        raise ValidationError("Search text must be 2 to 50 characters.")
    return text


def parse_priority(value) -> Priority:
    if isinstance(value, Priority):
        return value
    text = _clean(value).lower()
    for priority in Priority:
        if priority.value.lower() == text:
            return priority
    raise ValidationError("Priority must be one of: Critical, High, Medium, Low.")


def parse_status(value) -> Status:
    if isinstance(value, Status):
        return value
    text = _clean(value).lower().replace("-", " ").replace("_", " ")
    for status in Status:
        if status.value.lower() == text:
            return status
    raise ValidationError("Status must be one of: Open, In Progress, Closed.")


def parse_ticket_id(value) -> int:
    if isinstance(value, bool):
        raise ValidationError("Ticket ID must be a whole number, for example 12.")
    if isinstance(value, int):
        number = value
    else:
        text = _clean(value).lstrip("#")
        if not text.isdigit():
            raise ValidationError("Ticket ID must be a whole number, for example 12.")
        number = int(text)
    if not 1 <= number <= 2_000_000_000:
        raise ValidationError("Ticket ID must be a positive number.")
    return number
