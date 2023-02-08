import logging

from flask import Blueprint, make_response

import ckan.model as model
import ckan.plugins.toolkit as tk


log = logging.getLogger(__name__)
sitemap = Blueprint("sitemap", __name__)


@sitemap.route("/sitemap.xml")
@sitemap.route("/sitemap")
def index():
    sitemap_data = '<?xml version="1.0" encoding="UTF-8"?>\n'
    sitemap_data += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    host_url: str = tk.request.host_url.replace("http:", "https:").strip("/")

    for package in _get_packages():
        modified_at: str = package.metadata_modified.strftime("%Y-%m-%d")
        sitemap_data += (
            f"<url><loc>{host_url}/dataset/{package.name}</loc>"
            f"<lastmod>{modified_at}</lastmod></url>\n"
        )

    for organisation in model.Group.all("organization"):
        sitemap_data += (
            f"<url><loc>{host_url}/organization/{organisation.name}</loc></url>\n"
        )

    for group in model.Group.all("group"):
        sitemap_data += f"<url><loc>{host_url}/group/{group.name}</loc></url>\n"

    sitemap_data += "</urlset>"
    response = make_response(sitemap_data)
    response.headers["Content-Type"] = "application/xml"

    return response


def _get_packages():
    package = model.Package

    return (
        model.Session.query(package.name, package.metadata_modified)
        .filter(package.state == model.State.ACTIVE)
        .filter(package.private == False)
        .order_by(package.name)
        .all()
    )
