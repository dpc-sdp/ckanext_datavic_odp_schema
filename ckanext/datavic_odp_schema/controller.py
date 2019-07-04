from ckan.common import c, response
from ckan.controllers.package import PackageController
#import ckan.lib.package_saver as package_saver
#from ckan.lib.base import BaseController
import ckan.lib.base as base
import ckan.lib as lib
import ckan.logic as logic
import ckan.model as model

from ckanext.datavic_odp_theme import helpers

from ckan.controllers.api import ApiController


render = base.render
NotFound = logic.NotFound
NotAuthorized = logic.NotAuthorized
get_action = logic.get_action

class HistoricalController(PackageController):

    def historical(self, id):
        response.headers['Content-Type'] = "text/html; charset=utf-8"
        package_type = self._get_package_type(id.split('@')[0])

        context = {'model': model, 'session': model.Session,
                   'user': c.user or c.author, 'for_view': True,
                   'auth_user_obj': c.userobj}
        data_dict = {'id': id}
        # check if package exists
        try:
            c.pkg_dict = get_action('package_show')(context, data_dict)
            c.pkg = context['package']
        except NotFound:
            abort(404, _('Dataset not found'))
        except NotAuthorized:
            abort(401, _('Unauthorized to read package %s') % id)

        # used by disqus plugin
        c.current_package_id = c.pkg.id
        #c.related_count = c.pkg.related_count
        self._setup_template_variables(context, {'id': id},
                                       package_type=package_type)

        #package_saver.PackageSaver().render_package(c.pkg_dict, context)

        try:
            return render('package/read_historical.html')
        except lib.render.TemplateNotFound:
            msg = _("Viewing {package_type} datasets in {format} format is "
                    "not supported (template file {file} not found).".format(
                package_type=package_type, format=format, file='package/read_historical.html'))
            abort(404, msg)

        assert False, "We should never get here"

class FormatController(PackageController):

    def formats(self):
        return ApiController()._finish_ok(helpers.format_list())


class DateMigrateController(base.BaseController):

    def date_migrate(self):

        # postgresql: // ckan_default:ckan_default @ localhost / ckan_default

        # Use CKAN API
        from ckanapi import RemoteCKAN, LocalCKAN, ValidationError

        old_prod = RemoteCKAN('http://13.211.80.162/data/', apikey='2c4434a4-2f02-4efa-91af-e361ae55059c')

        id = 'fff14b41-4492-46e1-a2a9-e49177620d0a'

        # Fetch x# packages from Old IAR Prod - with info
        packages = old_prod.call_action('package_search', {'q': 'id:'+ id})

        # Loop through retrieved packages
        if packages['results']:
            from pprint import pprint
            for package in packages['results']:
                #pprint(package)
                print(package['id'])
                print(package['name'])
                print(package['metadata_created'])
                print(package['metadata_modified'])

                print("UPDATED package SET metadata_created = '%s' WHERE id = '%s'" % (package['metadata_created'], id))

        return 'done'

        # output the dataset id, name and created & modified dates




        output = ''

        import psycopg2
        try:
            connection = psycopg2.connect(user="ckan_default",
                                          password="ckan_default",
                                          host="localhost",
                                          port="5432",
                                          database="ckan_default")
            cursor = connection.cursor()
            # Print PostgreSQL Connection properties
            # print (connection.get_dsn_parameters(), "\n")
            # Print PostgreSQL version
            cursor.execute("SELECT version();")
            record = cursor.fetchone()
            print("You are connected to - ", record, "\n")

            print("Table Before updating record ")
            sql_select_query = """select * from package where id = %s"""
            cursor.execute(sql_select_query, ('1475a46c-6d2f-4058-9829-705afbfcbdfd', ))
            record = cursor.fetchone()
            print(record)
            # Update single record now
            sql_update_query = """Update package set metadata_created = %s, metadata_modified = %s where id = %s"""
            cursor.execute(sql_update_query, ('2018-05-02', '2018-06-03', '1475a46c-6d2f-4058-9829-705afbfcbdfd'))
            connection.commit()
            count = cursor.rowcount
            print(count, "Record Updated successfully ")
            print("Table After updating record ")
            sql_select_query = """select * from package where id = %s"""
            cursor.execute(sql_select_query, ('1475a46c-6d2f-4058-9829-705afbfcbdfd', ))
            record = cursor.fetchone()
            print(record)

        except (Exception, psycopg2.Error) as error:
            print ("Error while connecting to PostgreSQL", error)
        finally:
            # closing database connection.
            if (connection):
                cursor.close()
                connection.close()
                print("PostgreSQL connection is closed")


        return 'complete'