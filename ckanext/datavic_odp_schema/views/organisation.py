import logging

from flask import Blueprint

import ckan.plugins.toolkit as tk
import ckan.authz as authz
import ckan.model as model
import ckan.logic as logic

from ckan.lib.navl.dictization_functions import unflatten
import ckanext.datavic_odp_schema.organisation_helpers as organisation_helpers

NotFound = tk.ObjectNotFound
NotAuthorized = tk.NotAuthorized
ValidationError = tk.ValidationError
check_access = tk.check_access
get_action = tk.get_action

clean_dict = logic.clean_dict
tuplize_dict = logic.tuplize_dict
parse_params = logic.parse_params

render = tk.render
abort = tk.abort


ckanadmin_organisations = Blueprint("ckanadmin_organisations", __name__)


def admin():
    user = tk.g.userobj

    if not user or not authz.is_sysadmin(user.name):
        abort(403, tk._("You are not permitted to perform this action."))

    errors = []
    vars = {}

    if tk.request.method == "POST":
        data_dict = clean_dict(unflatten(tuplize_dict(parse_params(tk.request.form))))

        vars["data"] = data_dict

        source_url = data_dict.get("iar_url", None)
        api_key = data_dict.get("iar_api_key", None)

        if not source_url or not api_key:
            errors.append("Both URL and API Key must be set")
        if not organisation_helpers.valid_url(source_url):
            errors.append("Incorrect URL value")
        if organisation_helpers.contains_invalid_chars(api_key):
            errors.append("Incorrect API Key value")

        if len(errors):
            vars["errors"] = errors
        else:
            # Everything appears to be in order - time to reconcile
            context = {"model": model, "session": model.Session}
            vars["log"] = organisation_helpers.reconcile_local_organisations(
                context, source_url, api_key
            )

    return render("admin/organisations.html", extra_vars=vars)


def register_org_admin_rules(blueprint):
    blueprint.add_url_rule(
        "/ckan-admin/organisations", methods=["GET", "POST"], view_func=admin
    )


register_org_admin_rules(ckanadmin_organisations)
