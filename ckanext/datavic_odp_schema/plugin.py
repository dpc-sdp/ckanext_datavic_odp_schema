import logging

import ckan.plugins as p
import ckan.plugins.toolkit as tk

import ckanext.datavic_odp_schema.cli as cli
from ckanext.datavic_odp_schema.views import get_blueprints
from ckanext.datavic_odp_schema.helpers import get_helpers


log = logging.getLogger(__name__)


class DatavicODPSchema(p.SingletonPlugin):
    p.implements(p.ITemplateHelpers)
    p.implements(p.IConfigurer)
    p.implements(p.IBlueprint)
    p.implements(p.IClick)

    # IBlueprint
    def get_blueprint(self):
        return get_blueprints()

    # IConfigurer
    def update_config(self, config_):
        tk.add_template_directory(config_, "templates")

    # ITemplateHelpers
    def get_helpers(self):
        return get_helpers()

    # IClick
    def get_commands(self):
        return cli.get_commands()
