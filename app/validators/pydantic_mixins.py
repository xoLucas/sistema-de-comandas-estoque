"""Pydantic mixins for reusable Brazilian field validation.

These mixins are designed to be inherited by the Pydantic schemas declared
inside the API routers, keeping validation close to the request payload.
"""

from __future__ import annotations

from pydantic import field_validator

from app.validators.brazilian import (
    format_phone,
    is_valid_email,
    is_valid_phone,
    normalize_email,
    validate_contact,
    validate_document_by_customer_type,
)


class CustomerDocumentMixin:
    @field_validator("document", mode="before")
    @classmethod
    def validate_document(cls, value, info):
        customer_type = info.data.get("customer_type") or "pf"
        return validate_document_by_customer_type(value, customer_type)


class PhoneMixin:
    @field_validator("phone", mode="before")
    @classmethod
    def validate_phone(cls, value):
        if not value:
            return value
        if not is_valid_phone(value):
            raise ValueError("Telefone inválido")
        return format_phone(value)


class EmailMixin:
    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, value):
        if not value:
            return value
        if not is_valid_email(value):
            raise ValueError("E-mail inválido")
        return normalize_email(value)


class ContactMixin:
    @field_validator("contact", mode="before")
    @classmethod
    def validate_contact_field(cls, value):
        return validate_contact(value)


class CustomerValidationMixin(CustomerDocumentMixin, PhoneMixin, EmailMixin):
    """Combined mixin for customer schemas."""


class SupplierValidationMixin(ContactMixin):
    """Combined mixin for supplier schemas."""


class EmployeeValidationMixin(ContactMixin):
    """Combined mixin for employee schemas."""


# Settings keys that require domain validation.
_CNPJ_SETTINGS = {"store_cnpj"}
_PHONE_SETTINGS = {"store_phone"}
_EMAIL_SETTINGS = {"auto_report_email", "smtp_user", "smtp_from"}
_THEME_SETTINGS = {"theme_mode"}


def validate_setting_value(key: str, value: str | None) -> str | None:
    """Validate and format a setting value according to its semantic key."""
    if value is None:
        return value

    if key in _CNPJ_SETTINGS:
        return validate_document_by_customer_type(value, "pj")

    if key in _PHONE_SETTINGS:
        if not is_valid_phone(value):
            raise ValueError("Telefone inválido")
        return format_phone(value)

    if key in _EMAIL_SETTINGS:
        if not is_valid_email(value):
            raise ValueError("E-mail inválido")
        return normalize_email(value)

    if key in _THEME_SETTINGS:
        normalized = value.lower().strip()
        if normalized not in {"light", "dark"}:
            raise ValueError("Tema deve ser 'light' ou 'dark'")
        return normalized

    return value
