import logging

import ckan.plugins as p
import ckan.plugins.toolkit as tk

from ckanext.datavic_odp_schema import validators

log = logging.getLogger(__name__)


@tk.blanket.blueprints
@tk.blanket.cli
@tk.blanket.helpers
@tk.blanket.validators
class DatavicODPSchema(p.SingletonPlugin):
    p.implements(p.IConfigurer)

    # IConfigurer
    def update_config(self, config_):
        tk.add_template_directory(config_, "templates")
