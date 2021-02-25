from ckan.common import c, response, request
from ckan.controllers.package import PackageController
#import ckan.lib.package_saver as package_saver
#from ckan.lib.base import BaseController
import ckan.authz as authz
import ckan.lib.base as base
import ckan.lib as lib
import ckan.logic as logic
import ckan.model as model
import ckan.plugins.toolkit as toolkit
import sqlalchemy

from ckanext.datavic_odp_theme import helpers
import organization_helpers

from ckan.controllers.api import ApiController
from ckan.lib.navl.dictization_functions import unflatten

_select = sqlalchemy.sql.select
_and_ = sqlalchemy.and_


render = base.render
NotFound = logic.NotFound
NotAuthorized = logic.NotAuthorized
get_action = logic.get_action
clean_dict = logic.clean_dict
tuplize_dict = logic.tuplize_dict
parse_params = logic.parse_params
abort = base.abort
_ = base._

# class HistoricalController(PackageController):

#     def historical(self, id):
#         response.headers['Content-Type'] = "text/html; charset=utf-8"
#         package_type = self._get_package_type(id.split('@')[0])

#         context = {'model': model, 'session': model.Session,
#                    'user': c.user or c.author, 'for_view': True,
#                    'auth_user_obj': c.userobj}
#         data_dict = {'id': id}
#         # check if package exists
#         try:
#             c.pkg_dict = get_action('package_show')(context, data_dict)
#             c.pkg = context['package']
#         except NotFound:
#             abort(404, _('Dataset not found'))
#         except NotAuthorized:
#             abort(401, _('Unauthorized to read package %s') % id)

#         # used by disqus plugin
#         c.current_package_id = c.pkg.id
#         #c.related_count = c.pkg.related_count
#         self._setup_template_variables(context, {'id': id},
#                                        package_type=package_type)

#         #package_saver.PackageSaver().render_package(c.pkg_dict, context)

#         try:
#             return render('package/read_historical.html')
#         except lib.render.TemplateNotFound:
#             msg = _("Viewing {package_type} datasets in {format} format is "
#                     "not supported (template file {file} not found).".format(
#                 package_type=package_type, format=format, file='package/read_historical.html'))
#             abort(404, msg)

#         assert False, "We should never get here"


# class FormatController(PackageController):

#     def formats(self):
#         return ApiController()._finish_ok(helpers.format_list())


class SitemapController(base.BaseController):

    def sitemap(self):

        response.headers['Content-Type'] = 'application/xml'
        response.charset = 'UTF-8'
        sitemap = '<?xml version="1.0" encoding="UTF-8"?> \n'
        sitemap += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"> \n'

        package_table = model.package_table
        query = _select([package_table.c.name, package_table.c.metadata_modified])
        query = query.where(_and_(
            package_table.c.state == 'active',
            package_table.c.private == False,
        ))
        query = query.order_by(package_table.c.name)

        for package in query.execute():
            sitemap += '<url><loc>' + request.host_url.replace('http:','https:') + '/dataset/' + package.name + '</loc><lastmod>' + package.metadata_modified.strftime('%Y-%m-%d') + '</lastmod></url> \n'
        for organisation in model.Group.all('organization'):
            sitemap += '<url><loc>' + request.host_url.replace('http:','https:') + '/organization/' + organisation.name + '</loc></url> \n'
        for group in model.Group.all('group'):
            sitemap += '<url><loc>' + request.host_url.replace('http:','https:') + '/group/' + group.name + '</loc></url> \n'
        sitemap += '</urlset> \n'
        return sitemap


class OrganisationController(base.BaseController):

    def admin(self):
        # Only sysadmin users can generate reports
        user = toolkit.c.userobj

        if not user or not authz.is_sysadmin(user.name):
            abort(403, _('You are not permitted to perform this action.'))

        errors = []
        vars = {}

        if request.method == 'POST':
            data_dict = clean_dict(unflatten(
                tuplize_dict(parse_params(request.POST))))

            vars['data'] = data_dict

            source_url = data_dict.get('iar_url', None)
            api_key = data_dict.get('iar_api_key', None)

            if not source_url or not api_key:
                errors.append('Both URL and API Key must be set')
            if not organization_helpers.valid_url(source_url):
                errors.append('Incorrect URL value')
            if organization_helpers.contains_invalid_chars(api_key):
                errors.append('Incorrect API Key value')

            if len(errors):
                vars['errors'] = errors
            else:
                # Everything appears to be in order - time to reconcile
                context = {'model': model, 'session': model.Session}
                vars['log'] = organization_helpers.reconcile_local_organisations(context, source_url, api_key)

        return base.render('admin/organisations.html', extra_vars=vars)


