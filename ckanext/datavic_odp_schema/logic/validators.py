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
