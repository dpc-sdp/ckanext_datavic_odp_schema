import time
import calendar
import logging

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit

from datetime import datetime
from ckanext.datavic_odp_schema import schema as custom_schema
#from ckanext.datavic_odp_schema import historical

_t = toolkit._

log1 = logging.getLogger(__name__)


def parse_date(date_str):
    try:
        return calendar.timegm(time.strptime(date_str, "%Y-%m-%d"))
    except Exception, e:
        return None


class DatavicODPSchema(plugins.SingletonPlugin, toolkit.DefaultDatasetForm):
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IDatasetForm, inherit=True)
    plugins.implements(plugins.IRoutes, inherit=True)

    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        #toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('fanstatic', 'datavic-odp-schema')

    ## IConfigurer interface ##
    def update_config_schema(self, schema):
        schema.update({
            'ckan.datavic.authorised_resource_formats': [
                toolkit.get_validator('ignore_missing'),
                unicode
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
            'historical_resources_list': self.historical_resources_list,
            'historical_resources_range': self.historical_resources_range,
            'is_historical': self.is_historical,
            'get_formats': self.get_formats,
        }

    ## IConfigurer interface ##
    def get_formats(self, limit=100):
        try:
            # Get any additional formats added in the admin settings
            additional_formats = [x.strip() for x in config.get('ckan.datavic.authorised_resource_formats', []).split(',')]
            q = request.GET.get('q', '')
            list_of_formats = [x.encode('utf-8') for x in
                               logic.get_action('format_autocomplete')({}, {'q': q, 'limit': limit}) if x] + additional_formats
            list_of_formats = sorted(list(set(list_of_formats)))
            dict_of_formats = []
            for item in list_of_formats:
                if item == ' ' or item == '':
                    continue
                else:
                    dict_of_formats.append({'value': item.lower(), 'text': item.upper()})
            dict_of_formats.insert(0, {'value': '', 'text': 'Please select'})

        except Exception, e:
            return []
        else:
            return dict_of_formats



    # IRoutes
    def before_map(self, map):
        map.connect('dataset_historical', '/dataset/{id}/historical',
            controller='ckanext.datavic_odp_schema.controller:HistoricalController', action='historical')
        map.connect('format_list', '/api/3/action/format_list',
            controller='ckanext.datavic_odp_schema.controller:FormatController', action='formats')
        map.connect('/sitemap.xml',
            controller='ckanext.datavic_odp_schema.controller:SitemapController', action='sitemap')
        return map


    def historical_resources_list(self, resource_list):
        sorted_resource_list = {}
        i = 0
        for resource in resource_list:
            i += 1
            if resource.get('period_start') is not None and resource.get('period_start') != 'None' and resource.get(
                    'period_start') != '':
                key = parse_date(resource.get('period_start')[:10]) or 'zzz' + str(i)
            else:
                key = '9999999999' + str(i)
            resource['key'] = key
            # print parser.parse(resource.get('period_start')).strftime("%Y-%M-%d") + " " + resource.get('period_start')
            sorted_resource_list[key] = resource

        list = sorted(sorted_resource_list.values(), key=lambda item: int(item.get('key')), reverse=True)
        # for item in list:
        #    print item.get('period_start') + " " + str(item.get('key'))
        return list

    def historical_resources_range(self, resource_list):
        range_from = ""
        from_ts = None
        range_to = ""
        to_ts = None
        for resource in resource_list:

            if resource.get('period_start') is not None and resource.get('period_start') != 'None' and resource.get(
                    'period_start') != '':
                ts = parse_date(resource.get('period_start')[:10])
                if ts and (from_ts is None or ts < from_ts):
                    from_ts = ts
            if resource.get('period_end') is not None and resource.get('period_end') != 'None' and resource.get(
                    'period_end') != '':
                ts = parse_date(resource.get('period_end')[:10])
                if ts and (to_ts is None or ts > to_ts):
                    to_ts = ts

        if from_ts:
            range_from = datetime.fromtimestamp(from_ts).strftime("%d/%m/%Y")

        if to_ts:
            range_to = datetime.fromtimestamp(to_ts).strftime("%d/%m/%Y")

        if range_from != "" and range_to != "":
            return range_from + " to " + range_to
        elif range_from != "" or range_to != "":
            return range_from + range_to
        else:
            return None

    def is_historical(self):
        if toolkit.c.action == 'historical':
            return True

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
            items = filter(lambda t: t['key'] == key, extras_list)
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
        schema['title'] = [toolkit.get_validator('not_empty'), unicode]
        schema['notes'] = [toolkit.get_validator('not_empty'), unicode]

        if toolkit.c.controller in ['dataset', 'package'] and toolkit.c.action not in ['resource_edit', 'new_resource', 'resource_delete']:
            schema['tag_string'] = [toolkit.get_validator('not_empty'), toolkit.get_converter('tag_string_convert')]

        # Adjust validators for the Resource fields marked mandatory in the Data.Vic schema
        schema['resources']['format'] = [toolkit.get_validator('not_empty'), toolkit.get_validator('if_empty_guess_format'), toolkit.get_validator('clean_format'), unicode]

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
