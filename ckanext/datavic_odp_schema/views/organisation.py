from __future__ import annotations

from typing import Optional, Any

from flask import Blueprint

import ckan.plugins.toolkit as tk
import ckan.authz as authz
import ckan.model as model
import ckan.logic as logic

from ckan.lib.navl.dictization_functions import unflatten
import ckanext.datavic_odp_schema.organisation_helpers as organisation_helpers


clean_dict = logic.clean_dict
tuplize_dict = logic.tuplize_dict
parse_params = logic.parse_params

organisation = Blueprint("odp_admin", __name__)


@organisation.route(
    "/ckan-admin/organisations", methods=["GET", "POST"], endpoint="organisations"
)
def index():
    user: Optional[model.User] = tk.g.userobj

    if not user or not authz.is_sysadmin(user.name):
        return tk.abort(403, tk._("You are not permitted to perform this action."))

    errors: list[str] = []
    vars: dict[str, Any] = {}

    if tk.request.method != "POST":
        return tk.render("admin/organisations.html", extra_vars=vars)

    data_dict: dict[str, Any] = clean_dict(unflatten(tuplize_dict(parse_params(tk.request.form))))

    vars["data"] = data_dict

    source_url: Optional[str] = data_dict.get("iar_url")
    api_key: Optional[str] = data_dict.get("iar_api_key")

    if not source_url or not api_key:
        errors.append("Both URL and API Key must be set")
    if source_url and not organisation_helpers.valid_url(source_url):
        errors.append("Incorrect URL value")
    if api_key and not organisation_helpers.valid_api_key(api_key):
        errors.append("Incorrect API Key value")

    if errors:
        vars["errors"] = errors
    else:
        vars["log"] = organisation_helpers.reconcile_local_organisations(
            {"model": model, "session": model.Session}, source_url, api_key
        )

    return tk.render("admin/organisations.html", extra_vars=vars)
