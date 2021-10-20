import logging

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
import re

import ckanext.datavic_odp_schema.helpers as helpers

_t = toolkit._

log1 = logging.getLogger(__name__)

class DatavicODPSchema(plugins.SingletonPlugin, toolkit.DefaultDatasetForm):
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IConfigurer)
    # plugins.implements(plugins.IDatasetForm, inherit=True)
    plugins.implements(plugins.IRoutes, inherit=True)
    plugins.implements(plugins.IPackageController, inherit=True)
    plugins.implements(plugins.IBlueprint)

    # IBlueprint
    def get_blueprint(self):
        return helpers._register_blueprints()

    # IConfigurer

    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        # toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('webassets', 'datavic-odp-schema')
        # toolkit.add_ckan_admin_tab(config_, 'ckanadmin_organisations', 'Org. tools')

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
        }

    # IDatasetForm interface ##
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

    def after_show(self, context, pkg_dict):
        """
        DATAVIC-232: Remove custodian details before showing or indexing dataset
        """
        pkg_dict.pop('maintainer', None)
        pkg_dict.pop('maintainer_email', None)

        return pkg_dict
