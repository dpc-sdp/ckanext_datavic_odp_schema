# Format (tuple): ( 'field_id', { 'field_attribute': 'value' } )
RESOURCE_EXTRA_FIELDS = [
    # Last updated is a core field..
    # ('last_updated', {'label': 'Last Updated'}),
    ('filesize', {'label': 'Filesize'}),
    ('release_date', {'label': 'Release Date', 'field_type': 'date'}),
    ('period_start', {'label': 'Temporal Coverage Start', 'field_type': 'date'}),
    ('period_end', {'label': 'Temporal Coverage End', 'field_type': 'date'}),
    ('data_quality', {'label': 'Data Quality Statement', 'field_type': 'textarea'}),
    ('attribution', {'label': 'Attribution Statement', 'field_type': 'textarea'}),
]

# Format (tuple): ( 'field_id', { 'field_attribute': 'value' } )
DATASET_EXTRA_FIELDS = [
    # License
    ('custom_licence_text', {'label': 'License - other', 'field_group': 'licence'}),
    #('custom_licence_link', {'label': 'Custom license link', 'field_group': 'licence'}),
    ('date_created_data_asset', {'label': 'Created (Data Asset)', 'field_type': 'date', 'required': True}),
]


def get_options(option_list):
    options = []
    if option_list is not None:
        for option in option_list:
            options.append(option.get('value'))
    return options


def get_option_label(type, field, value):
    if type == 'dataset':
        schema = DATASET_EXTRA_FIELDS
    else:
        schema = RESOURCE_EXTRA_FIELDS

    for element in schema:
        if element[0] == field:
            schema_field = element
            break

    if schema_field and 'options' in schema_field[1]:
        for option in schema_field[1]['options']:
            if option['value'] == value:
                value = option['text']
                break
    return value
