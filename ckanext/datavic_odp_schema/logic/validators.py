"""Custom validators for ODP dataset schema."""

import ckan.plugins.toolkit as tk


def required_if_license_other(key, data, errors, context):
    """
    Require the current field to be non-empty when license_id is "other".
    """
    license_id = data.get(("license_id",))
    if license_id is tk.missing or not license_id:
        return

    if str(license_id).strip().lower() != "other":
        return

    value = data.get(key)
    if value is tk.missing or value is None or (isinstance(value, str) and not value.strip()):
        errors[key].append(tk._("Missing value"))


def url_email_validator(key, data, errors, context):
    """
    Validate that the value, when provided, is a valid email or URL.
    """
    value = data.get(key)
    if value is tk.missing or value is None or (isinstance(value, str) and not value.strip()):
        # Optional field: empty values are allowed.
        return

    value = value.strip() if isinstance(value, str) else str(value).strip()

    # Try to validate as email
    try:
        tk.get_validator("email_validator")(value, context)
        return
    except tk.Invalid:
        pass

    # Try to validate as URL
    if tk.h.is_url(value):
        return

    errors[key].append(tk._("Must be a valid email address or URL"))
