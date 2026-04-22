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
    p.implements(p.IPackageController, inherit=True)

    # IConfigurer
    def update_config(self, config_):
        tk.add_template_directory(config_, "templates")

    # IPackageController
    def after_dataset_show(self, context, pkg_dict):
        pkg_dict.pop("maintainer_email", None)
        return pkg_dict

    def after_dataset_search(self, search_results, search_params):
        for item in search_results.get("results", []):
            item.pop("maintainer_email", None)
        return search_results
