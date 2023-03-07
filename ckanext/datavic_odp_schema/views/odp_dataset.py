import logging

from flask import Blueprint

import ckan.model as model
import ckan.plugins.toolkit as tk

import ckan.views.api as api
from ckan.views.dataset import _get_package_type, _setup_template_variables

from ckanext.datavic_odp_theme import helpers


log = logging.getLogger(__name__)
odp_dataset = Blueprint("odp_dataset", __name__)


@odp_dataset.route("/dataset/<id>/historical")
def historical(id):
    context = {
        "model": model,
        "session": model.Session,
        "user": tk.g.user or tk.g.author,
        "for_view": True,
        "auth_user_obj": tk.g.userobj,
    }

    try:
        pkg_dict = tk.get_action("package_show")(context, {"id": id})
    except tk.ObjectNotFound:
        return tk.abort(404, tk._("Dataset not found"))
    except tk.NotAuthorized:
        return tk.abort(401, tk._("Unauthorized to read package {}").format(id))

    return tk.render(
        "package/read_historical.html",
        {"pkg_dict": pkg_dict, "pkg": context["package"]},
    )


@odp_dataset.route("/api/action/format_list")
def formats():
    return api._finish(200, helpers.format_list(), content_type="json")
