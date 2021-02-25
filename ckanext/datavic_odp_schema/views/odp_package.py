import logging
from operator import itemgetter

from flask import Blueprint

import ckan.lib.helpers as h
import ckan.model as model
from ckan.common import _,  g
import ckan.plugins.toolkit as toolkit

import ckan.views.dataset as dataset
import ckan.views.api as api

from ckanext.datavic_odp_theme import helpers

NotFound = toolkit.ObjectNotFound
NotAuthorized = toolkit.NotAuthorized
ValidationError = toolkit.ValidationError
check_access = toolkit.check_access
get_action = toolkit.get_action


render = toolkit.render
abort = toolkit.abort

log = logging.getLogger(__name__)

odp_package = Blueprint('odp_package', __name__)


def historical(id):
    package_type = dataset._get_package_type(id.split('@')[0])

    context = {'model': model, 'session': model.Session,
                'user': g.user or g.author, 'for_view': True,
                'auth_user_obj': g.userobj}
    data_dict = {'id': id}
    # check if package exists
    try:
        pkg_dict = get_action('package_show')(context, data_dict)
        pkg = context['package']
    except NotFound:
        abort(404, _('Dataset not found'))
    except NotAuthorized:
        abort(401, _('Unauthorized to read package %s') % id)

    # used by disqus plugin
    current_package_id = pkg.id
    #c.related_count = c.pkg.related_count
    dataset._setup_template_variables(context, {'id': id},
                                    package_type=package_type)

    #package_saver.PackageSaver().render_package(c.pkg_dict, context)

    try:
        return render('package/read_historical.html')
    except NotFound:
        msg = _("Viewing {package_type} datasets in {format} format is "
                "not supported (template file {file} not found).".format(
            package_type=package_type, format=format, file='package/read_historical.html'))
        abort(404, msg)

    assert False, "We should never get here"

def formats():
    data = helpers.format_list()
    return api._finish(200, data, content_type='json')


def register_odp_dataset_plugin_rules(blueprint):
    blueprint.add_url_rule('/dataset/<id>/historical', view_func=historical)
    blueprint.add_url_rule('/api/action/format_list', view_func=formats)

register_odp_dataset_plugin_rules(odp_package)
