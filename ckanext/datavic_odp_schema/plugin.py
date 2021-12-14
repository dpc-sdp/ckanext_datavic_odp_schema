import logging

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit

import ckanext.datavic_odp_schema.helpers as helpers
import ckaext.datavic_odp_schema.cli as cli


log = logging.getLogger(__name__)


class DatavicODPSchema(plugins.SingletonPlugin, toolkit.DefaultDatasetForm):
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IBlueprint)
    plugins.implements(plugins.IClick)

    # IBlueprint
    def get_blueprint(self):
        return helpers._register_blueprints()

    # IConfigurer
    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_resource('webassets', 'datavic-odp-schema')
        toolkit.add_ckan_admin_tab(config_, 'ckanadmin_organisations.admin', 'Org. tools')

    # IConfigurer interface ##
    def update_config_schema(self, schema):
        schema.update({
            'ckan.datavic.authorised_resource_formats': [
                toolkit.get_validator('ignore_missing'),
                str
            ],
        })

        return schema

    # ITemplateHelpers interface ##
    def get_helpers(self):
        ''' Return a dict of named helper functions (as defined in the ITemplateHelpers interface).
        These helpers will be available under the 'h' thread-local global object.
        '''
        return {
            'historical_resources_list': helpers.historical_resources_list,
            'historical_resources_range': helpers.historical_resources_range,
            'is_historical': helpers.is_historical,
            'get_formats': helpers.get_formats,
            'dataset_fields': helpers.dataset_fields('dataset')
        }
    
    # IClick
    def get_commands(self):
        return cli.get_commands()
