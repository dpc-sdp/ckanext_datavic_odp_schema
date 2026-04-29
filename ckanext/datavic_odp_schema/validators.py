from ckan.plugins import toolkit as tk
from ckanext.scheming.validation import register_validator


@register_validator
def datavic_filesize_validator(key, data, errors, context):
    value = data.get(key)
    if value:
        try:
            data[key] = int(value)
        except (TypeError, ValueError):
            errors[key].append(
                "Enter file size in bytes (numeric values only), or leave blank"
            )


@register_validator
def datavic_tag_string_convert(key, data, errors, context):
    """
    Validates the tag_string field and converts into tags only if coming from the dataset form, not the resource form
    """
    if context.get('save'):
        tk.get_validator('not_empty')(key, data, errors, context)
        tk.get_validator('tag_string_convert')(key, data, errors, context)
