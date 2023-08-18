import logging

from flask import Blueprint

import ckan.plugins.toolkit as tk
import ckan.views.api as api
from ckan import types

from ckanext.datavic_odp_theme import helpers


log = logging.getLogger(__name__)
odp_dataset = Blueprint("odp_dataset", __name__)


@odp_dataset.route("/<package_type>/<package_id>/historical")
def historical(package_type: str, package_id: str):
    context: types.Context = tk.fresh_context({})

    data_dict = {"id": package_id}

    try:
        pkg_dict = tk.get_action("package_show")(context, data_dict)

    except tk.ObjectNotFound:
        return tk.abort(404, tk._("Dataset not found"))
    except tk.NotAuthorized:
        return tk.abort(401, tk._(f"Unauthorized to read package {package_id}"))

    return tk.render("package/read_historical.html", {"pkg_dict": pkg_dict})


@odp_dataset.route("/api/action/format_list")
def formats():
    return api._finish(200, helpers.format_list(), content_type="json")
