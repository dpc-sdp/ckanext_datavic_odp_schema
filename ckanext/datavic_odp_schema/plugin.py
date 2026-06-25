import logging

import ckan.plugins as p
import ckan.plugins.toolkit as tk

from ckanext.datavic_odp_schema import validators

log = logging.getLogger(__name__)


def _action_context():
    """Return the CKAN action context stored on the current SQLAlchemy session."""
    try:
        session = tk.ckan.model.Session()
        return getattr(session, "_context", None) or {}
    except Exception:
        return {}


def _is_api_request():
    return bool(_action_context().get("api_version"))


def _strip_custodian_fields(pkg_dict):
    pkg_dict.pop("maintainer_email", None)
    pkg_dict.pop("data_owner", None)


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
        if _is_api_request():
            _strip_custodian_fields(pkg_dict)
        return pkg_dict

    def after_dataset_search(self, search_results, search_params):
        if _is_api_request():
            for item in search_results.get("results", []):
                _strip_custodian_fields(item)
        return search_results
