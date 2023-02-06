import ckan.logic as logic
import ckan.model as model
import ckan.plugins.toolkit as toolkit
from ckan.lib.cli import CkanCommand
from ckanapi import CKANAPIError, RemoteCKAN
from pprint import pprint

ValidationError = logic.ValidationError
NotFound = logic.NotFound


class MigrateFullMetadataUrl(CkanCommand):
    """Migrates the `full_metadata_url` from IAR datasets to ODP counterparts"""

    summary = __doc__.split("\n")[0]

    errors = []

    def __init__(self, name):
        super(MigrateFullMetadataUrl, self).__init__(name)
        self.parser.add_option(
            "-s",
            "--source_url",
            dest="source_url",
            help="Remote CKAN source URL",
            type=str,
            default=None,
        )
        self.parser.add_option(
            "-k",
            "--api_key",
            dest="api_key",
            help="Remote CKAN source API Key",
            type=str,
            default=None,
        )
        self.parser.add_option(
            "-l",
            "--limit",
            dest="limit",
            help="Limit the number of datasets to process",
            type=int,
            default=100,
        )
        self.parser.add_option(
            "-o",
            "--offset",
            dest="offset",
            help="Offset for the number of datasets to process",
            type=int,
            default=0,
        )

    def separator(self):
        print("----------------------------------------")

    def fetch_local_package(self, context, package_name):
        local_package = None
        try:
            local_package = toolkit.get_action("package_show")(
                context, {"id": package_name}
            )
        except NotFound:
            print("- Local package name %s not found." % package_name)
        except ValueError as e:
            self.errors.append(str(e))
        return local_package

    def fetch_remote_package(self, source_url, api_key, package_name):
        source = RemoteCKAN(source_url, apikey=api_key)
        remote_package = None
        try:
            remote_package = source.action.package_show(id=package_name)
        except NotFound:
            print("- No remote package found for package ID %s." % package_name)
        except CKANAPIError as e:
            self.errors.append(str(e))
        return remote_package

    def get_package_names(self, limit, offset):
        packages = toolkit.get_action("package_list")(
            data_dict={"limit": limit, "offset": offset}
        )

        return packages

    def patch_package(self, package_id, full_metadata_url):
        try:
            toolkit.get_action("package_patch")(
                data_dict={"id": package_id, "full_metadata_url": full_metadata_url}
            )
            return True
        except ValidationError as e:
            print("- Validation Error %s" % e)
        return False

    def command(self):
        """

        :return:
        """
        self._load_config()

        context = {"session": model.Session}

        source_url = self.options.source_url
        api_key = self.options.api_key
        limit = self.options.limit
        offset = self.options.offset

        if not source_url:
            print("Remote source not specified. Exiting.")
            return

        # Get all the local package names.
        package_names = self.get_package_names(limit, offset)

        num_packages_updated = 0

        self.separator()

        for package_name in package_names:
            print("Processing local package name: %s" % package_name)

            # Load local package
            local_package = self.fetch_local_package(context, package_name)

            if not local_package:
                continue

            # Don't bother updating local package if it already has a value set for `full_metadata_url`
            if local_package.get("full_metadata_url", None):
                print(
                    "- Local package %s has `full_metadata_url` set to %s - nothing to do."
                    % (package_name, local_package.get("full_metadata_url"))
                )
                continue

            print(
                "- Local package name %s does not have existing `full_metadata_url` - attempting to fetch..."
                % package_name
            )

            # Fetch matching package by ID from remote source
            remote_package = self.fetch_remote_package(
                source_url, api_key, package_name
            )

            if not remote_package:
                continue

            full_metadata_url = remote_package.get("full_metadata_url", None)

            if not full_metadata_url:
                print(
                    "- `full_metadata_url` not found in remote package - nothing to do."
                )
                continue

            pprint(remote_package.get("full_metadata_url", None))

            result = self.patch_package(package_name, full_metadata_url)

            if result:
                num_packages_updated += 1

            self.separator()

        self.separator()
        print("Number of packages updated: %s" % num_packages_updated)
        self.separator()

        if self.errors:
            pprint(self.errors)
        else:
            print("No Errors")

        self.separator()

        return "FINISHED."
