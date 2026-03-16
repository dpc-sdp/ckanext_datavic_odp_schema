"""Custom validators for ODP dataset schema."""

import ckan.plugins.toolkit as tk

from urllib.parse import urlparse
from ckan.logic.validators import email_validator as ckan_email_validator
from ckan.lib.navl.dictization_functions import Invalid


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
    Validate that the value is non-empty and either a valid email or a valid URL.
    """
    value = data.get(key)
    if value is tk.missing or value is None or (isinstance(value, str) and not value.strip()):
        errors[key].append(tk._("Missing value"))
        return

    value = value.strip() if isinstance(value, str) else str(value).strip()

    # Try to validate as email
    try:
        ckan_email_validator(value, context)
        return
    except Invalid:
        pass

    # Try to validate as URL
    try:
        parsed = urlparse(value)
        if parsed.scheme and parsed.netloc and parsed.scheme in ("http", "https"):
            return
    except (ValueError, TypeError):
        pass

    errors[key].append(tk._("Must be a valid email address or URL"))
