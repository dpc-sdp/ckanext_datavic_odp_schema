import logging
from operator import itemgetter

from flask import Blueprint, make_response
import sqlalchemy

import ckan.model as model
import ckan.plugins.toolkit as toolkit

from ckanext.datavic_odp_theme import helpers

NotFound = toolkit.ObjectNotFound
NotAuthorized = toolkit.NotAuthorized
ValidationError = toolkit.ValidationError
check_access = toolkit.check_access
get_action = toolkit.get_action

_select = sqlalchemy.sql.select
_and_ = sqlalchemy.and_


render = toolkit.render
abort = toolkit.abort

log = logging.getLogger(__name__)

sitemap = Blueprint('sitemap', __name__)

def sitemaps():
    sitemap_data = '<?xml version="1.0" encoding="UTF-8"?> \n'
    sitemap_data += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"> \n'

    package_table = model.package_table
    query = _select([package_table.c.name, package_table.c.metadata_modified])
    query = query.where(_and_(
        package_table.c.state == 'active',
        package_table.c.private == False,
    ))
    query = query.order_by(package_table.c.name)

    for package in query.execute():
        sitemap_data += '<url><loc>' + toolkit.request.host_url.replace('http:','https:') + '/dataset/' + package.name + '</loc><lastmod>' + package.metadata_modified.strftime('%Y-%m-%d') + '</lastmod></url> \n'
    for organisation in model.Group.all('organization'):
        sitemap_data += '<url><loc>' + toolkit.request.host_url.replace('http:','https:') + '/organization/' + organisation.name + '</loc></url> \n'
    for group in model.Group.all('group'):
        sitemap_data += '<url><loc>' + toolkit.request.host_url.replace('http:','https:') + '/group/' + group.name + '</loc></url> \n'
    sitemap_data += '</urlset> \n'
    response = make_response(sitemap_data)
    response.headers["Content-Type"] = "application/xml"
    return response

sitemap.add_url_rule('/sitemap.xml', view_func=sitemaps)    
sitemap.add_url_rule('/sitemap', view_func=sitemaps) 