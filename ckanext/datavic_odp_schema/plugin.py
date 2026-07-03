import logging

import ckan.plugins as p
import ckan.plugins.toolkit as tk

from ckanext.datavic_odp_schema import validators

log = logging.getLogger(__name__)


def _session_context():
    """Fallback for hooks that receive no context (e.g. after_dataset_search)."""
    try:
        session = tk.ckan.model.Session()
        return getattr(session, "_context", None) or {}
    except Exception:
        return {}


def _is_api_request(context=None):
    """True for public API reads; false for internal write-time reads (for_update) or non-API calls."""
    ctx = context if context is not None else _session_context()
    return bool(ctx.get("api_version")) and not ctx.get("for_update")


def _strip_custodian_fields(pkg_dict):
    """Remove sensitive custodian fields before returning a package dict to the public API."""
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
        if _is_api_request(context):
            _strip_custodian_fields(pkg_dict)
        return pkg_dict

    def after_dataset_search(self, search_results, search_params):
        if _is_api_request():
            for item in search_results.get("results", []):
                _strip_custodian_fields(item)
        return search_results
