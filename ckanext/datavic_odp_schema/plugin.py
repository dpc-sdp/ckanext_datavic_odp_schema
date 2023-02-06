import logging

import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit

import ckanext.datavic_odp_schema.helpers as helpers
import ckanext.datavic_odp_schema.cli as cli


log = logging.getLogger(__name__)


class DatavicODPSchema(plugins.SingletonPlugin):
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IBlueprint)
    plugins.implements(plugins.IClick)

    # IBlueprint
    def get_blueprint(self):
        return helpers._register_blueprints()

    # IConfigurer
    def update_config(self, config_):
        toolkit.add_template_directory(config_, "templates")
        toolkit.add_ckan_admin_tab(
            config_, "ckanadmin_organisations.admin", "Org. tools"
        )

    # ITemplateHelpers
    def get_helpers(self):
        return {
            "historical_resources_list": helpers.historical_resources_list,
            "historical_resources_range": helpers.historical_resources_range,
            "is_historical": helpers.is_historical,
            "is_other_license": helpers.is_other_license,
        }

    # IClick
    def get_commands(self):
        return cli.get_commands()
