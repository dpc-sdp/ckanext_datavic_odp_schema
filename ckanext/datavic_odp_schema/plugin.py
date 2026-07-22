import logging

import ckan.authz as authz
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


def _is_sysadmin(context=None):
    """Return True if the requesting user is a sysadmin, False otherwise (fail-closed)."""
    ctx = context if context is not None else _session_context()
    user = ctx.get("user")
    if not user:
        return False
    try:
        return authz.is_sysadmin(user)
    except Exception:
        log.warning(
            "Could not determine sysadmin status for custodian stripping",
            exc_info=True,
        )
        return False


def _strip_custodian_fields(pkg_dict, is_sysadmin=False):
    """Strip custodian fields from a package dict for public API responses.

    maintainer_email is always removed; data_owner is kept for sysadmins.
    """
    pkg_dict.pop("maintainer_email", None)
    if not is_sysadmin:
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
            _strip_custodian_fields(pkg_dict, is_sysadmin=_is_sysadmin(context))
        return pkg_dict

    def after_dataset_search(self, search_results, search_params):
        if _is_api_request():
            is_sysadmin = _is_sysadmin()
            for item in search_results.get("results", []):
                _strip_custodian_fields(item, is_sysadmin=is_sysadmin)
        return search_results
