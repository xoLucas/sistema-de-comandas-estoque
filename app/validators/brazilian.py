"""Brazilian document and contact validators.

This module provides pure functions to validate and format CPF, CNPJ,
phone numbers and e-mail addresses commonly used throughout the system.
"""

from __future__ import annotations

import re


_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_numbers(value: str | None) -> str:
    """Return only digits from *value* or an empty string."""
    if not value:
        return ""
    return re.sub(r"\D", "", str(value))


def _all_same_digit(digits: str) -> bool:
    return len(set(digits)) == 1


def is_valid_cpf(value: str | None) -> bool:
    """Validate a Brazilian CPF (with or without formatting)."""
    digits = clean_numbers(value)
    if len(digits) != 11 or _all_same_digit(digits):
        return False

    # First verifier digit
    total = sum(int(digits[i]) * (10 - i) for i in range(9))
    first = 11 - (total % 11)
    if first >= 10:
        first = 0
    if first != int(digits[9]):
        return False

    # Second verifier digit
    total = sum(int(digits[i]) * (11 - i) for i in range(10))
    second = 11 - (total % 11)
    if second >= 10:
        second = 0
    if second != int(digits[10]):
        return False

    return True


def format_cpf(value: str | None) -> str | None:
    """Return the CPF formatted as XXX.XXX.XXX-XX, or *value* unchanged."""
    digits = clean_numbers(value)
    if len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    return value


def is_valid_cnpj(value: str | None) -> bool:
    """Validate a Brazilian CNPJ (with or without formatting)."""
    digits = clean_numbers(value)
    if len(digits) != 14 or _all_same_digit(digits):
        return False

    first_weights = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    total = sum(int(digits[i]) * first_weights[i] for i in range(12))
    first = 11 - (total % 11)
    if first >= 10:
        first = 0
    if first != int(digits[12]):
        return False

    second_weights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    total = sum(int(digits[i]) * second_weights[i] for i in range(13))
    second = 11 - (total % 11)
    if second >= 10:
        second = 0
    if second != int(digits[13]):
        return False

    return True


def format_cnpj(value: str | None) -> str | None:
    """Return the CNPJ formatted as XX.XXX.XXX/XXXX-XX, or *value* unchanged."""
    digits = clean_numbers(value)
    if len(digits) == 14:
        return (
            f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/"
            f"{digits[8:12]}-{digits[12:]}"
        )
    return value


def is_valid_email(value: str | None) -> bool:
    """Validate a basic e-mail format."""
    if not value:
        return False
    return bool(_EMAIL_PATTERN.match(str(value).strip()))


def normalize_email(value: str | None) -> str | None:
    """Trim and lowercase a valid e-mail address."""
    if not value:
        return value
    return str(value).strip().lower()


def is_valid_phone(value: str | None) -> bool:
    """Validate a Brazilian phone number.

    Accepts landlines (10 digits) and mobile phones (11 digits),
    optionally prefixed with the country code 55.
    """
    digits = clean_numbers(value)
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    return len(digits) in (10, 11)


def format_phone(value: str | None) -> str | None:
    """Return the phone formatted as (XX) XXXX-XXXX or (XX) XXXXX-XXXX."""
    digits = clean_numbers(value)
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]

    if len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    return value


def validate_contact(value: str | None) -> str | None:
    """Validate and format a generic contact field.

    Detects whether the value looks like an e-mail or a phone number and
    validates accordingly. Returns the normalized/formatted value or raises
    ValueError when invalid.
    """
    if not value:
        return value

    text = str(value).strip()
    if "@" in text:
        if not is_valid_email(text):
            raise ValueError("E-mail inválido")
        return normalize_email(text)

    if not is_valid_phone(text):
        raise ValueError("Telefone inválido")
    return format_phone(text)


def validate_document_by_customer_type(
    value: str | None, customer_type: str
) -> str | None:
    """Validate and format a document based on the customer type.

    * customer_type == "pf" -> requires a valid CPF
    * customer_type == "pj" -> requires a valid CNPJ
    * any other type -> accepts either CPF or CNPJ
    """
    if not value:
        return value

    digits = clean_numbers(value)
    customer_type = (customer_type or "pf").lower()

    if customer_type == "pf":
        if len(digits) != 11 or not is_valid_cpf(digits):
            raise ValueError("CPF inválido")
        return format_cpf(digits)

    if customer_type == "pj":
        if len(digits) != 14 or not is_valid_cnpj(digits):
            raise ValueError("CNPJ inválido")
        return format_cnpj(digits)

    # Fallback: accept either CPF or CNPJ when type is unknown
    if len(digits) == 11 and is_valid_cpf(digits):
        return format_cpf(digits)
    if len(digits) == 14 and is_valid_cnpj(digits):
        return format_cnpj(digits)

    raise ValueError("Documento deve ser um CPF ou CNPJ válido")
