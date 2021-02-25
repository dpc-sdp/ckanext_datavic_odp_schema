import logging

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
import re

import ckanext.datavic_odp_schema.helpers as helpers
from ckanext.datavic_odp_schema import schema as custom_schema

_t = toolkit._

log1 = logging.getLogger(__name__)


class DatavicODPSchema(plugins.SingletonPlugin, toolkit.DefaultDatasetForm):
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IDatasetForm, inherit=True)
    plugins.implements(plugins.IRoutes, inherit=True)
    plugins.implements(plugins.IPackageController, inherit=True)
    plugins.implements(plugins.IBlueprint)


    #IBlueprint
    def get_blueprint(self):
        return helpers._register_blueprints()

    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        #toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('webassets', 'datavic-odp-schema')
        #toolkit.add_ckan_admin_tab(config_, 'ckanadmin_organisations', 'Org. tools')

    ## IConfigurer interface ##
    def update_config_schema(self, schema):
        schema.update({
            'ckan.datavic.authorised_resource_formats': [
                toolkit.get_validator('ignore_missing'),
                str
            ],
        })

        return schema

    ## ITemplateHelpers interface ##

    def get_helpers(self):
        ''' Return a dict of named helper functions (as defined in the ITemplateHelpers interface).
        These helpers will be available under the 'h' thread-local global object.
        '''
        return {
            'dataset_extra_fields': custom_schema.DATASET_EXTRA_FIELDS,
            'resource_extra_fields': custom_schema.RESOURCE_EXTRA_FIELDS,
            'historical_resources_list': helpers.historical_resources_list,
            'historical_resources_range': helpers.historical_resources_range,
            'is_historical': helpers.is_historical,
            'get_formats': helpers.get_formats,
        }


    ## IDatasetForm interface ##

    def is_fallback(self):
        '''
        Return True to register this plugin as the default handler for
        package types not handled by any other IDatasetForm plugin.
        '''
        return True

    def package_types(self):
        '''
        This plugin doesn't handle any special package types, it just
        registers itself as the default (above).
        '''
        return []

    def _modify_package_schema(self, schema):
        ''' Override CKAN's create/update schema '''

        # Define some closures as custom callbacks for the validation process

        from ckan.lib.navl.dictization_functions import missing, StopOnError, Invalid

        # DataVic: Helper function for adding extra dataset fields
        def append_field(extras_list, data, key):
            items = list(filter(lambda t: t['key'] == key, extras_list))
            if items:
                items[0]['value'] = data.get((key,))
            else:
                extras_list.append({ 'key': key, 'value': data.get((key,)) })
            return

        def after_validation_processor(key, data, errors, context):
            assert key[0] == '__after', 'This validator can only be invoked in the __after stage'
            #raise Exception ('Breakpoint after_validation_processor')
            # Demo of howto create/update an automatic extra field
            extras_list = data.get(('extras',))
            if not extras_list:
                extras_list = data[('extras',)] = []

            # # Note Append "record_modified_at" field as a non-input field
            # datestamp = time.strftime('%Y-%m-%d %T')
            # items = filter(lambda t: t['key'] == 'record_modified_at', extras_list)
            # if items:
            #     items[0]['value'] = datestamp
            # else:
            #     extras_list.append({ 'key': 'record_modified_at', 'value': datestamp })

            # DataVic: Append extra fields as dynamic (not registered under modify schema) field
            for field in custom_schema.DATASET_EXTRA_FIELDS:
                append_field(extras_list, data, field[0])

            if toolkit.c.controller == 'package' and toolkit.c.action in ['new', 'edit']:
                # Validate our custom schema fields based on the rules set in schema.py
                for custom_field in custom_schema.DATASET_EXTRA_FIELDS:
                    field_id = custom_field[0]
                    field_attributes = custom_field[1]
                    # Check required fields
                    if field_attributes.get('required', None) is True:
                        value = data.get((field_id,))
                        if not value:
                            errors[(field_id,)] = [u'Missing value']
                    # Ensure submitted value for select / drop-down is valid
                    if field_attributes.get('field_type', None) == 'select':
                        value = data.get((field_id,), None)
                        options = custom_schema.get_options(field_attributes.get('options', None))
                        if value not in options:
                            errors[(field_id,)] = [u'Invalid option']


        def before_validation_processor(key, data, errors, context):
            assert key[0] == '__before', 'This validator can only be invoked in the __before stage'
            #raise Exception ('Breakpoint before_validation_processor')
            # Note Add dynamic field (not registered under modify schema) "foo.x1" to the fields
            # we take into account. If we omitted this step, the ('__extras',) item would have
            # been lost (along with the POSTed value).
            # DataVic: Add extra fields..
            for field in custom_schema.DATASET_EXTRA_FIELDS:
                data[(field[0],)] = data[('__extras',)].get(field[0])
            pass

        # Add our custom_resource_text metadata field to the schema
        # schema['resources'].update({
        #     'custom_resource_text' : [ toolkit.get_validator('ignore_missing') ]
        # })
        # DataVic implementation of adding extra metadata fields to resources
        resources_extra_metadata_fields = {}
        for field in custom_schema.RESOURCE_EXTRA_FIELDS:
            # DataVic: no custom validators for extra metadata fields at the moment
            resources_extra_metadata_fields[field[0]] = [ toolkit.get_validator('ignore_missing') ]

        schema['resources'].update(resources_extra_metadata_fields)

        # Add callbacks to the '__after' pseudo-key to be invoked after all key-based validators/converters
        if not schema.get('__after'):
            schema['__after'] = []
        schema['__after'].append(after_validation_processor)

        # A similar hook is also provided by the '__before' pseudo-key with obvious functionality.
        if not schema.get('__before'):
            schema['__before'] = []
        # any additional validator must be inserted before the default 'ignore' one.
        schema['__before'].insert(-1, before_validation_processor) # insert as second-to-last

        # Adjust validators for the Dataset/Package fields marked mandatory in the Data.Vic schema
        schema['title'] = [toolkit.get_validator('not_empty'), str]
        schema['notes'] = [toolkit.get_validator('not_empty'), str]

        if toolkit.c.controller in ['dataset', 'package'] and toolkit.c.action not in ['resource_edit', 'new_resource', 'resource_delete']:
            schema['tag_string'] = [toolkit.get_validator('not_empty'), toolkit.get_converter('tag_string_convert')]

        # Adjust validators for the Resource fields marked mandatory in the Data.Vic schema
        schema['resources']['format'] = [toolkit.get_validator('not_empty'), toolkit.get_validator('if_empty_guess_format'), toolkit.get_validator('clean_format'), str]

        return schema

    def create_package_schema(self):
        schema = super(DatavicODPSchema, self).create_package_schema()
        schema = self._modify_package_schema(schema)
        return schema

    def update_package_schema(self):
        schema = super(DatavicODPSchema, self).update_package_schema()
        schema = self._modify_package_schema(schema)
        return schema

    def show_package_schema(self):
        schema = super(DatavicODPSchema, self).show_package_schema()

        # Don't show vocab tags mixed in with normal 'free' tags
        # (e.g. on dataset pages, or on the search page)
        schema['tags']['__extras'].append(toolkit.get_converter('free_tags_only'))

        # Create a dictionary containing the extra fields..
        dict_extra_fields = {
            # # Add our non-input field (created at after_validation_processor)
            # 'record_modified_at': [
            #     toolkit.get_converter('convert_from_extras'),
            # ],
        }

        # Loop through our extra fields, adding them to the schema..
        # Applying the same validator to them for now..
        for field in custom_schema.DATASET_EXTRA_FIELDS:
            dict_extra_fields[field[0]] = [
                toolkit.get_converter('convert_from_extras'),
                toolkit.get_validator('ignore_missing')
            ]

        # Apply any specific rules / validators that we know of..
        #

        schema.update(dict_extra_fields)


        # Update Resource schema
        schema['resources'].update({
            'custom_resource_text': [ toolkit.get_validator('ignore_missing') ],
            'period_start': [toolkit.get_converter('convert_from_extras'),
                             toolkit.get_validator('ignore_missing')],
            'period_end': [toolkit.get_converter('convert_from_extras'),
                           toolkit.get_validator('ignore_missing')],
        })

        return schema

    # IPackageController

    def after_show(self, context, pkg_dict):
        """
        DATAVIC-232: Remove custodian details before showing or indexing dataset
        """
        pkg_dict.pop('maintainer', None)
        pkg_dict.pop('maintainer_email', None)

        return pkg_dict
