from __future__ import annotations

import csv
import datetime
import logging
from typing import Any
from urllib.parse import urlparse

import click
import os
import shutil
import tqdm
from sqlalchemy.exc import SQLAlchemyError

import ckan.logic as logic
import ckan.model as model
import ckan.plugins.toolkit as tk
from ckan.lib.uploader import get_resource_uploader, get_uploader
from ckan.model import Resource, ResourceView

from ckanext.datastore.backend import get_all_resources_ids_in_datastore

from ckanext.datavic_odp_schema.helpers import localized_filesize

log = logging.getLogger(__name__)

# Relative to ckan.storage_path.
FILESTORE_AUDIT_OUTPUT_DIR = "audit_reports"


@click.group()
def maintain():
    """Portal maintenance tasks"""
    pass


@maintain.command("ckan-drop-harvster-tables")
def ckan_drop_harvester_tables():
    """Delete all tables and data related to harvester."""

    harvest_sources = model.Session.execute("SELECT * FROM harvest_source")
    for source in harvest_sources:
        _delete_harvester_source(source.id)

    model.Session.execute(
        "DROP TABLE IF EXISTS harvest_log, harvest_object_error, harvest_gather_error, harvest_object, harvest_job, harvest_object_extra, harvest_source CASCADE;"
    )
    model.Session.execute("DROP type IF EXISTS  log_level;")

    try:
        model.Session.commit()
        click.secho("ckanext-harvest table removed successfully", fg="green")
    except SQLAlchemyError:
        click.secho("DB Error: Failed to drop ckanext-harvest tables", fg="red")
        model.Session.rollback()


def _delete_harvester_source(harvest_source_id: str):
    """Delete entries for harvester package.
    Args:
        harvest_source_id (str) : harvester source id.
    Returns:
        none
    """

    user = tk.get_action("get_site_user")({"ignore_auth": True}, {})

    try:
        tk.get_action("dataset_purge")(
            {"user": user["name"]}, {"id": harvest_source_id}
        )
        click.secho(
            f"removed harvester source {harvest_source_id} successfully", fg="green"
        )
    except tk.ObjectNotFound:
        click.secho(
            f"DB Error: Failed to remove ckanext-harvest source: {harvest_source_id}",
            fg="red",
        )


@maintain.command("get-broken-recline")
def identify_resources_with_broken_recline():
    """Return a list of resources with a broken recline_view"""

    query = (
        model.Session.query(model.Resource)
        .join(
            model.ResourceView,
            model.ResourceView.resource_id == model.Resource.id,
        )
        .filter(
            model.ResourceView.view_type.in_(
                ["datatables_view", "recline_view"]
            )
        )
    )

    resources = [resource for resource in query.all()]

    if not resources:
        return click.secho("No resources with inactive datastore")

    for resource in resources:
        if resource.extras.get("datastore_active"):
            continue

        res_url = tk.url_for(
            "resource.read",
            id=resource.package_id,
            resource_id=resource.id,
            _external=True,
        )
        click.secho(
            f"Resource {res_url} has a table view but datastore is inactive",
            fg="green",
        )

        
@maintain.command("recline-to-datatable")
@click.option("-d", "--delete", is_flag=True, help="Delete recline_view views")
def replace_recline_with_datatables(delete: bool):
    """Replaces recline_view with datatables_view
    Args:
        delete (bool): delete existing `recline_view` views
    """
    resources = [
        res
        for res in model.Session.query(Resource).all()
        if res.extras.get("datastore_active")
    ]
    if not resources:
        click.secho("No resources have been found", fg="green")
        return click.secho(
            "NOTE: `datatables_view` works only with resources uploaded to datastore",
            fg="green",
        )
    click.secho(
        f"{len(resources)} resources have been found. Updating views...",
        fg="green",
    )
    with tqdm.tqdm(resources) as bar:
        for res in bar:
            res_views = _get_existing_views(res.id)
            if not _is_datatable_view_exist(res_views):
                _create_datatable_view(res.id)
            if delete:
                _delete_recline_views(res_views)


def _get_existing_views(resource_id: str) -> list[ResourceView]:
    """Returns a list of resource view entities
    Args:
        resource_id (str): resource ID
    Returns:
        list[ResourceView]: list of resource views
    """
    return (
        model.Session.query(ResourceView)
        .filter(ResourceView.resource_id == resource_id)
        .all()
    )


def _is_datatable_view_exist(res_views: list[ResourceView]) -> bool:
    """Checks if at least one view from resource views is `datatables_view`
    Args:
        res_views (list[ResourceView]): list of resource views
    Returns:
        bool: True if `datatables_view` view exists
    """
    for view in res_views:
        if view.view_type == "datatables_view":
            return True
    return False


def _create_datatable_view(resource_id: str):
    """Creates a datatable view for resource
    Args:
        resource_id (str): resource ID
    """
    tk.get_action("resource_view_create")(
        {"ignore_auth": True},
        {
            "resource_id": resource_id,
            "show_fields": _get_resource_fields(resource_id),
            "title": "Datatable",
            "view_type": "datatables_view",
        },
    )


def _get_resource_fields(resource_id: str) -> list[str]:
    """Fetches list of resource fields from datastore
    Args:
        resource_id (str): resource ID
    Returns:
        list[str]: list of resource fields
    """
    ctx = {"ignore_auth": True}
    data_dict = {
        "resource_id": resource_id,
        "limit": 0,
        "include_total": False,
    }
    try:
        search = tk.get_action("datastore_search")(ctx, data_dict)
    except tk.ObjectNotFound:
        click.echo(f"Resource {resource_id} orphaned")
        return []

    fields = [field for field in search["fields"]]
    return [f["id"] for f in fields]


def _delete_recline_views(res_views: list[ResourceView]):
    for view in res_views:
        if view.view_type != "recline_view":
            continue
        view.delete()
    model.repo.commit()


@maintain.command("purge-deleted-datasets", short_help="Purge deleted datasets by type")
@click.argument("type")
def purge_deleted_datasets(type: str):
    """Removes deleted datasets of certain type from db entirely

    Args:
        type (str): type of datasets to be purged
    """
    log.info(f"Searching for deleted datasets of <{type}> type...")

    datasets = (
        model.Session.query(model.Package.id, model.Package.title)
        .filter(model.Package.type == type)
        .filter(model.Package.state == "deleted")
        .all()
    )

    if not datasets:
        click.secho(f"No datasets of <{type}> type were founded", fg="green")
    else:
        click.secho(
            f"{len(datasets)} deleted datasets of <{type}> type were founded.",
            fg="green",
        )
        for dataset in datasets:
            site_user = logic.get_action("get_site_user")({"ignore_auth": True}, {})
            context = {"user": site_user["name"], "ignore_auth": True}
            logic.get_action("dataset_purge")(context, {"id": dataset[0]})
            click.secho(f"{dataset[0]} '{dataset[1]}' - purged", fg="yellow")

        click.secho("Done.", fg="green")


@maintain.command("purge-empty-orgs")
def purge_empty_organizations():
    """Purge organizations without any datasets"""
    result = tk.get_action("organization_list")(
        {"ignore_auth": True}, {"all_fields": True}
    )

    empty_orgs = [org for org in result if org["package_count"] == 0]

    if not empty_orgs:
        return click.secho("No empty organization.", fg="green")

    click.secho(f"Found {len(empty_orgs)} empty organization(s). Purging...")

    for org_dict in empty_orgs:
        tk.get_action("organization_purge")(
            {"ignore_auth": True}, {"id": org_dict["id"]}
        )


@maintain.command("get-broken-recline")
def identify_resources_with_broken_recline():
    """Return a list of resources with a broken recline_view"""

    query = (
        model.Session.query(model.Resource)
        .join(
            model.ResourceView,
            model.ResourceView.resource_id == model.Resource.id,
        )
        .filter(model.ResourceView.view_type.in_(["datatables_view", "recline_view"]))
    )

    resources = [resource for resource in query.all()]

    if not resources:
        return click.secho("No resources with inactive datastore")

    for resource in resources:
        if resource.extras.get("datastore_active"):
            continue

        res_url = tk.url_for(
            "resource.read",
            id=resource.package_id,
            resource_id=resource.id,
            _external=True,
        )
        click.secho(
            f"Resource {res_url} has a table view but datastore is inactive",
            fg="green",
        )


@maintain.command
def delete_datastore_tables_with_no_related_resource():
    """Delete from Datastore all tables that do not have a related resource."""
    res_ids = _get_datastore_tables_with_no_related_resource()

    if not res_ids:
        click.secho(
            "Nothing to delete. "
            "All Datastore tables are associated with an existing resource",
            fg="green",
        )
        return

    for res_id in res_ids:
        try:
            click.secho(f"Deleting Datastore table with ID {res_id}", fg="green")
            tk.get_action("datastore_delete")(
                {"ignore_auth": True}, {"resource_id": res_id, "force": True}
            )
        except tk.ObjectNotFound:
            continue


@maintain.command
def list_datastore_tables_with_no_related_resource():
    """Show all Datastore tables that do not have a related resource."""
    res_ids = _get_datastore_tables_with_no_related_resource()

    if not res_ids:
        click.secho(
            "All Datastore tables are associated with an existing resource", fg="green"
        )
        return

    for res_id in res_ids:
        click.secho(f"{res_id}", fg="red")
    click.secho(
        f"Total number of Datastore tables that don't have a related resource is "
        f"{len(res_ids)}",
        fg="green",
    )


def _get_datastore_tables_with_no_related_resource() -> list[str]:
    """Return a list of Datastore table names that are not associated with
    the currently active resource."""
    res_ids = []
    for res_id in get_all_resources_ids_in_datastore():
        res = model.Resource.get(res_id)
        if not res or res.state == model.State.DELETED:
            res_ids.append(res_id)
    return res_ids


@maintain.command("make-datatables-view-prioritized")
def make_datatables_view_prioritized():
    """Check if there are resources that have recline_view and datatables_view and
    reorder them so that datatables_view is first."""
    resources = model.Session.query(Resource).all()
    number_reordered = 0
    for resource in tqdm.tqdm(resources):
        result = tk.get_action("datavic_datatables_view_prioritize")(
            {"ignore_auth": True}, {"resource_id": resource.id}
        )
        if result.get("updated"):
            number_reordered += 1
    click.secho(f"Reordered {number_reordered} resources", fg="green")


@maintain.command("cleanup-group-images")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List unused images without moving them.",
)
def cleanup_group_images(dry_run: bool):
    """Move unused group/organisation images to a _unused subdirectory.

    Fetches all organisations and groups, collects their image_url values,
    then compares against files on disk.  Any file not referenced by an active
    org or group is moved to <storage_path>/_unused for safe manual review.
    """
    storage_path = get_uploader("group").storage_path

    if dry_run:
        click.secho("Dry-run mode — no files will be moved.", fg="blue")

    try:
        referenced = _collect_referenced_group_images()
    except Exception as e:
        click.secho(f"Aborting: could not collect referenced images: {e}", fg="red")
        log.error("cleanup-group-images aborted during collection: %s", e)
        return

    click.secho(
        f"Found {len(referenced)} referenced image filename(s) across all orgs/groups.",
        fg="green",
    )

    if not os.path.isdir(storage_path):
        click.secho(f"Storage path does not exist: {storage_path}", fg="red")
        return

    unused_dir = os.path.join(storage_path, "_unused")

    disk_files: list[str] = []
    for filename in os.listdir(storage_path):
        filepath = os.path.join(storage_path, filename)
        if not os.path.isfile(filepath):
            continue
        disk_files.append(filename)

    unused: list[str] = []
    for filename in disk_files:
        if filename not in referenced:
            unused.append(filename)

    if not unused:
        click.secho("No unused images found.", fg="green")
        return

    click.secho(f"Found {len(unused)} unused image(s).", fg="yellow")

    if dry_run:
        for filename in unused:
            click.secho(f"  Would move: {filename}", fg="yellow")
        return

    os.makedirs(unused_dir, exist_ok=True)

    moved = 0
    skipped = 0
    failed = 0
    for filename in unused:
        src = os.path.join(storage_path, filename)
        dst = os.path.join(unused_dir, filename)
        if os.path.exists(dst):
            click.secho(
                f"  Skipped (already in _unused): {filename}", fg="yellow"
            )
            log.warning(
                "cleanup-group-images: skipped %s — destination already exists",
                filename,
            )
            skipped += 1
            continue
        try:
            shutil.move(src, dst)
            click.secho(f"  Moved: {filename}", fg="yellow")
            moved += 1
        except OSError as e:
            click.secho(f"  ERROR moving {filename}: {e}", fg="red")
            log.error("Failed to move group image %s: %s", filename, e)
            failed += 1

    click.secho(
        f"\nDone. {moved} moved, {skipped} skipped (already in _unused),"
        f" {failed} failed.",
        fg="green" if failed == 0 else "yellow",
    )


def _collect_referenced_group_images() -> set[str]:
    """Return the set of image filenames referenced by all orgs and groups.

    Raises an exception if the top-level list call for either orgs or groups
    fails, so the caller can abort rather than treating all files as unused.
    """
    ctx = {"ignore_auth": True}
    referenced: set[str] = set()

    actions = [
        ("organization_list", "organization_show"),
        ("group_list", "group_show"),
    ]

    for list_action, detail_action in actions:
        names: list[str] = tk.get_action(list_action)(ctx, {"all_fields": False})

        for name in names:
            try:
                data = tk.get_action(detail_action)(
                    ctx, {"id": name, "include_datasets": False}
                )
            except Exception as e:
                log.warning(
                    "Could not fetch %s for %s: %s", detail_action, name, e
                )
                continue

            value = data.get("image_url") or ""
            if value:
                referenced.add(os.path.basename(value.rstrip("/")))

    return referenced


@maintain.command("audit-filestore")
@click.option(
    "--purge-orphanage",
    is_flag=True,
    help="Move files not referenced in the database to orphanage under ckan.storage_path.",
)
def audit_filestore(purge_orphanage: bool = False):
    """Audit filestore usage and database references, writing CSV reports.

    Reports are written to audit_reports under ckan.storage_path.
    Existing reports are overwritten. With --purge-orphanage, unreferenced
    files are moved after the baseline reports are written.
    """

    # Validate storage configuration before creating the report directory.
    storage_path = tk.config.get("ckan.storage_path")
    if not storage_path:
        click.secho("ckan.storage_path is not configured.", fg="red")
        return

    storage_path = os.path.realpath(storage_path)
    output_dir = os.path.join(storage_path, FILESTORE_AUDIT_OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)

    # Use the same UTC measurement time for this run.
    measured_at = (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    # Inventory disk files, then match absolute paths against database references.
    files, errors = _filestore_audit_scan(storage_path)
    _filestore_audit_mark_database_references(files)
    # Calculate overall totals and per-namespace summaries.
    total_files = len(files)
    total_size = 0
    for item in files:
        total_size += item["size_bytes"]
    namespace_rows = _filestore_audit_namespace_summary(
        storage_path, files, total_size
    )

    # Write one row per file with its reference flags.
    _filestore_audit_write_csv(
        os.path.join(output_dir, "files.csv"),
        [
            "namespace",
            "path",
            "exists_in_database",
            "resource_in_trash",
            "size_bytes",
            "size_human",
            "last_modified",
        ],
        _filestore_audit_file_report_rows(files),
    )
    # Write counts and sizes grouped by namespace.
    _filestore_audit_write_csv(
        os.path.join(output_dir, "namespace-summary.csv"),
        [
            "namespace",
            "path",
            "file_count",
            "size_bytes",
            "size_human",
            "percentage_of_filestore",
            "exists_in_database_file_count",
            "exists_in_database_size_bytes",
            "exists_in_database_size_human",
            "exists_in_database_percentage",
            "resource_in_trash_file_count",
            "resource_in_trash_size_bytes",
            "resource_in_trash_size_human",
            "resource_in_trash_percentage",
            "not_exists_in_database_file_count",
            "not_exists_in_database_size_bytes",
            "not_exists_in_database_size_human",
            "not_exists_in_database_percentage",
        ],
        namespace_rows,
    )
    # Write overall totals for this run.
    _filestore_audit_write_csv(
        os.path.join(output_dir, "summary.csv"),
        [
            "measured_at",
            "storage_path",
            "total_file_count",
            "total_size_bytes",
            "total_size_human",
            "exists_in_database_file_count",
            "exists_in_database_size_bytes",
            "exists_in_database_size_human",
            "exists_in_database_percentage",
            "resource_in_trash_file_count",
            "resource_in_trash_size_bytes",
            "resource_in_trash_size_human",
            "resource_in_trash_percentage",
            "not_exists_in_database_file_count",
            "not_exists_in_database_size_bytes",
            "not_exists_in_database_size_human",
            "not_exists_in_database_percentage",
        ],
        [
            {
                "measured_at": measured_at,
                "storage_path": storage_path,
                "total_file_count": total_files,
                "total_size_bytes": total_size,
                "total_size_human": localized_filesize(total_size),
                **_filestore_audit_database_summary(files, total_size),
            }
        ],
    )
    # Write filesystem errors to identify incomplete scan coverage.
    _filestore_audit_write_csv(
        os.path.join(output_dir, "scan-errors.csv"),
        ["path", "error"],
        errors,
    )
    # Write database uploads whose expected files are absent.
    _filestore_audit_write_csv(
        os.path.join(output_dir, "missing-resource-files.csv"),
        [
            "resource_id",
            "resource_name",
            "resource_state",
            "resource_url",
            "resource_size_bytes",
            "resource_size_human",
            "missing_file_relative_path",
            "expected_file_path",
            "dataset_id",
            "dataset_title",
            "dataset_state",
            "organization_title",
            "data_owner",
            "contact_point",
        ],
        _filestore_audit_missing_resource_rows(storage_path),
    )

    # Check that grouping preserved the complete scanned inventory.
    counted_files = 0
    counted_size = 0
    for row in namespace_rows:
        counted_files += row["file_count"]
        counted_size += row["size_bytes"]
    if counted_files != total_files or counted_size != total_size:
        click.secho("Namespace totals do not match file inventory.", fg="red")
        return

    click.secho(f"Wrote filestore baseline to {output_dir}", fg="green")
    click.secho(
        f"Files: {total_files:,}; size: {localized_filesize(total_size)}",
        fg="green",
    )
    if errors:
        click.secho(
            f"Scan completed with {len(errors):,} errors; see scan-errors.csv",
            fg="yellow",
        )

    if purge_orphanage:
        _filestore_audit_move_orphans(storage_path, files, output_dir)


def _filestore_audit_orphanage_path() -> str:
    """Resolve the orphanage inside the configured CKAN filestore."""
    return os.path.join(os.path.realpath(tk.config["ckan.storage_path"]), "orphanage")


def _filestore_audit_move_orphans(
    storage_path: str, files: list[dict[str, Any]], output_dir: str
) -> None:
    """Move unreferenced files, preserving their storage-relative directory tree."""
    orphanage = _filestore_audit_orphanage_path()
    moved = skipped = failed = 0
    # Flush each result so a partial run still leaves a useful move log.
    report_path = os.path.join(output_dir, "orphanage-moves.csv")
    with open(report_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["namespace", "source", "destination", "status", "error"]
        )
        writer.writeheader()
        for item in files:
            if item["exists_in_database"] or item["resource_in_trash"]:
                continue
            source = item["path"]
            relative_path = os.path.relpath(source, storage_path)
            destination = os.path.join(orphanage, relative_path)
            row = dict(namespace=item["namespace"], source=source,
                       destination=destination, status="", error="")
            try:
                if relative_path == os.pardir or relative_path.startswith(os.pardir + os.sep):
                    raise ValueError("Source is outside the configured filestore")
                if os.path.islink(source) or not os.path.isfile(source):
                    raise ValueError("Source is no longer a regular file")
                # Reject symlinked destination directories that escape the orphanage.
                if not _filestore_audit_is_in_path(
                    os.path.realpath(os.path.dirname(destination)), os.path.realpath(orphanage)
                ):
                    raise ValueError("Destination directory escapes the orphanage")
                if os.path.lexists(destination):
                    row["status"] = "skipped"
                    row["error"] = "Destination already exists"
                    skipped += 1
                else:
                    os.makedirs(os.path.dirname(destination), exist_ok=True)
                    shutil.move(source, destination)
                    row["status"] = "moved"
                    moved += 1
            except (OSError, ValueError, shutil.Error) as exc:
                row["status"] = "failed"
                row["error"] = str(exc)
                failed += 1
            writer.writerow(row)
            handle.flush()
    click.echo(f"Orphanage: {orphanage}; {moved} moved, {skipped} skipped, {failed} failed.")
    if failed:
        raise click.ClickException(f"Some files could not be moved; see {report_path}")


def _filestore_audit_is_in_path(file_path: str, absolute_directory: str) -> bool:
    """Check whether an absolute path matches a directory or lies beneath it."""
    return file_path == absolute_directory or file_path.startswith(
        absolute_directory.rstrip(os.sep) + os.sep
    )


def _filestore_audit_file_row(
    namespace: str,
    absolute_path: str,
) -> dict[str, Any]:
    """Read file metadata and build an inventory row for its absolute path."""
    stat_result = os.stat(absolute_path, follow_symlinks=False)
    last_modified = (
        datetime.datetime.fromtimestamp(stat_result.st_mtime, datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return {
        "namespace": namespace,
        "path": os.path.abspath(absolute_path),
        "size_bytes": stat_result.st_size,
        "last_modified": last_modified,
    }


def _filestore_audit_namespaces() -> dict[str, dict[str, Any]]:
    """Define each scan directory and its database reference collector together."""
    namespaces = {
        "resource": {
            "path": "resources",
            "collector": _filestore_audit_resource_paths,
        },
        "group": {
            "path": "storage/uploads/group",
            "collector": _filestore_audit_group_image_paths,
        },
        "user": {
            "path": "storage/uploads/user",
            "collector": _filestore_audit_user_image_paths,
        },
    }
    return namespaces


def _filestore_audit_resource_paths(relative_directory: str) -> set[str]:
    """Collect resource paths using CKAN's uploader instead of relative_directory."""
    paths: set[str] = set()
    resource_ids = (
        model.Session.query(model.Resource.id)
        .filter(model.Resource.url_type == "upload")
        .all()
    )
    for resource_id, in resource_ids:
        if resource_id:
            paths.add(_filestore_audit_resource_path(resource_id))
    return paths


def _filestore_audit_resource_path(resource_id: str) -> str:
    """Resolve an absolute resource file path through CKAN's uploader."""
    return get_resource_uploader({}).get_path(resource_id)


def _filestore_audit_group_image_paths(relative_directory: str) -> set[str]:
    """Collect image paths referenced by groups and organizations."""
    return _filestore_audit_upload_image_paths(model.Group.image_url, relative_directory)


def _filestore_audit_user_image_paths(relative_directory: str) -> set[str]:
    """Collect image paths referenced by user profiles."""
    return _filestore_audit_upload_image_paths(model.User.image_url, relative_directory)


def _filestore_audit_upload_image_paths(column: Any, relative_directory: str) -> set[str]:
    """Collect image paths referenced by a database column under the given relative directory."""
    paths: set[str] = set()
    for value, in model.Session.query(column).filter(column != "").all():
        _filestore_audit_add_referenced_path(paths, relative_directory, value)
    return paths


def _filestore_audit_add_referenced_path(
    paths: set[str],
    relative_directory: str,
    value: Any,
) -> None:
    """Normalize an upload reference into an absolute path and add it to the set."""
    if not value:
        return

    # Extract the URL path, ignoring query strings and fragments.
    value_path = urlparse(str(value).strip()).path.strip("/")
    if not value_path:
        return

    storage_path = os.path.realpath(tk.config["ckan.storage_path"])
    # Accept references with the full storage-relative directory.
    if value_path.startswith(f"{relative_directory}/"):
        paths.add(os.path.join(storage_path, value_path))
        return

    # Public upload URLs omit the leading storage/ directory.
    upload_url_directory = relative_directory.removeprefix("storage/")
    if value_path.startswith(f"{upload_url_directory}/"):
        paths.add(os.path.join(storage_path, "storage", value_path))
        return

    # Treat other nonempty references as filenames in this upload namespace.
    basename = os.path.basename(value_path.rstrip("/"))
    if basename:
        paths.add(os.path.join(storage_path, relative_directory, basename))


def _filestore_audit_database_paths() -> dict[str, set[str]]:
    """Collect database references using the namespace registry."""
    database_paths: dict[str, set[str]] = {}
    for name, namespace in _filestore_audit_namespaces().items():
        collector = namespace["collector"]
        database_paths[name] = collector(relative_directory=namespace["path"])
    return database_paths


def _filestore_audit_deleted_resource_paths() -> set[str]:
    """Collect absolute file paths for uploaded resources marked as deleted."""
    paths: set[str] = set()
    resource_ids = (
        model.Session.query(model.Resource.id)
        .filter(model.Resource.url_type == "upload")
        .filter(model.Resource.state == "deleted")
        .all()
    )
    for resource_id, in resource_ids:
        if resource_id:
            paths.add(_filestore_audit_resource_path(resource_id))
    return paths


def _filestore_audit_mark_database_references(
    files: list[dict[str, Any]],
) -> None:
    """Load database references and add reference/trash flags to inventory rows."""
    database_paths = _filestore_audit_database_paths()
    deleted_resource_paths = _filestore_audit_deleted_resource_paths()

    for item in files:
        namespace_paths = database_paths.get(item["namespace"], set())
        item["exists_in_database"] = (
            item["path"] in namespace_paths
        )
        item["resource_in_trash"] = (
            item["path"] in deleted_resource_paths
        )


def _filestore_audit_file_report_rows(
    files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Format inventory rows for CSV, including yes/no flags and readable sizes."""
    rows: list[dict[str, Any]] = []
    for item in files:
        row = {
            "namespace": item["namespace"],
            "path": item["path"],
            "exists_in_database": "yes" if item["exists_in_database"] else "no",
            "resource_in_trash": "yes" if item["resource_in_trash"] else "no",
            "size_bytes": item["size_bytes"],
            "size_human": localized_filesize(item["size_bytes"]),
            "last_modified": item["last_modified"],
        }
        rows.append(row)
    return rows


def _filestore_audit_database_summary(
    files: list[dict[str, Any]],
    total_size: int,
) -> dict[str, Any]:
    """Summarize referenced, unreferenced, and trashed file counts and sizes."""
    exists_file_count = 0
    exists_size = 0
    resource_in_trash_file_count = 0
    resource_in_trash_size = 0

    # Trashed resources are also database references, so these categories overlap.
    for item in files:
        if item["exists_in_database"]:
            exists_file_count += 1
            exists_size += item["size_bytes"]
        if item["resource_in_trash"]:
            resource_in_trash_file_count += 1
            resource_in_trash_size += item["size_bytes"]

    # Unreferenced totals are the remainder of the scanned inventory.
    not_exists_file_count = len(files) - exists_file_count
    not_exists_size = total_size - exists_size

    return {
        "exists_in_database_file_count": exists_file_count,
        "exists_in_database_size_bytes": exists_size,
        "exists_in_database_size_human": localized_filesize(exists_size),
        "exists_in_database_percentage": (
            f"{exists_size / total_size * 100:.2f}" if total_size else "0.00"
        ),
        "resource_in_trash_file_count": resource_in_trash_file_count,
        "resource_in_trash_size_bytes": resource_in_trash_size,
        "resource_in_trash_size_human": localized_filesize(
            resource_in_trash_size
        ),
        "resource_in_trash_percentage": (
            f"{resource_in_trash_size / total_size * 100:.2f}"
            if total_size
            else "0.00"
        ),
        "not_exists_in_database_file_count": not_exists_file_count,
        "not_exists_in_database_size_bytes": not_exists_size,
        "not_exists_in_database_size_human": localized_filesize(not_exists_size),
        "not_exists_in_database_percentage": (
            f"{not_exists_size / total_size * 100:.2f}"
            if total_size
            else "0.00"
        ),
    }


def _filestore_audit_missing_resource_rows(
    storage_path: str,
) -> list[dict[str, Any]]:
    """Build report rows for uploaded resources whose expected files are missing."""
    resources = (
        model.Session.query(model.Resource)
        .filter(model.Resource.url_type == "upload")
        .order_by(model.Resource.id)
        .all()
    )
    rows: list[dict[str, Any]] = []

    for resource in resources:
        # Use CKAN's upload path and report only missing files.
        expected_file_path = _filestore_audit_resource_path(resource.id)
        if os.path.exists(expected_file_path):
            continue

        # Include dataset and owner details to help identify the missing upload.
        package = resource.package
        organization = (
            model.Group.get(package.owner_org)
            if package and package.owner_org
            else None
        )
        resource_size = resource.size

        rows.append(
            {
                "resource_id": resource.id,
                "resource_name": resource.name or "",
                "resource_state": resource.state or "",
                "resource_url": (
                    f"/dataset/{package.name}/resource/{resource.id}"
                    if package
                    else ""
                ),
                "resource_size_bytes": (
                    resource_size if resource_size is not None else ""
                ),
                "resource_size_human": (
                    localized_filesize(resource_size)
                    if resource_size is not None
                    else ""
                ),
                "missing_file_relative_path": os.path.relpath(
                    expected_file_path, storage_path
                ),
                "expected_file_path": os.path.abspath(expected_file_path),
                "dataset_id": package.id if package else "",
                "dataset_title": package.title if package else "",
                "dataset_state": package.state if package else "",
                "organization_title": organization.title if organization else "",
                "data_owner": (
                    package.extras.get("data_owner", "") if package else ""
                ),
                "contact_point": (
                    package.extras.get("contact_point", "") if package else ""
                ),
            }
        )

    return rows


def _filestore_audit_scan_directory(
    absolute_root: str,
    namespace: str,
    ignored_paths: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Recursively inventory regular files, skipping symlinks and collecting errors."""
    files: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    absolute_root = os.path.abspath(absolute_root)

    if not os.path.exists(absolute_root):
        return files, errors
    if not os.path.isdir(absolute_root):
        return files, [
            {
                "path": os.path.abspath(absolute_root),
                "error": "Configured scan path is not a directory",
            }
        ]

    # Traverse subdirectories using a stack of absolute paths.
    stack = [absolute_root]
    while stack:
        abs_dir = stack.pop()
        try:
            with os.scandir(abs_dir) as entries:
                for entry in entries:
                    # Prune excluded directories before descending into them.
                    is_ignored = False
                    if ignored_paths:
                        for ignored_path in ignored_paths:
                            if _filestore_audit_is_in_path(entry.path, ignored_path):
                                is_ignored = True
                                break

                    if is_ignored:
                        continue
                    try:
                        # Skip links so their targets are not counted again.
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                        # Record regular files only; directories have no inventory row.
                        if entry.is_file(follow_symlinks=False):
                            files.append(
                                _filestore_audit_file_row(
                                    namespace,
                                    entry.path,
                                )
                            )
                    # Record the error and continue with other accessible paths.
                    except OSError as e:
                        errors.append(
                            {
                                "path": os.path.abspath(entry.path),
                                "error": repr(e),
                            }
                        )
        # Record the error and continue with other accessible paths.
        except OSError as e:
            errors.append(
                {
                    "path": os.path.abspath(abs_dir),
                    "error": repr(e),
                }
            )

    return files, errors


def _filestore_audit_scan(storage_path: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Scan known storage roots and classify unmatched files there as UNKNOWN."""
    files: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    # Full namespace directories to exclude from the later UNKNOWN scan.
    # Example: /app/filestore/resources.
    orphanage_paths = {_filestore_audit_orphanage_path()}
    known_paths: set[str] = set(orphanage_paths)
    namespaces = _filestore_audit_namespaces()
    for namespace in namespaces.values():
        relative_path = namespace["path"]
        if relative_path.strip("/"):
            known_paths.add(os.path.join(storage_path, relative_path))

    # Scan each configured directory with its own namespace label.
    for name, namespace in namespaces.items():
        relative_root = namespace["path"]
        namespace_files, namespace_errors = _filestore_audit_scan_directory(
            os.path.join(storage_path, relative_root),
            name,
            ignored_paths=orphanage_paths,
        )
        files.extend(namespace_files)
        errors.extend(namespace_errors)

    # Deduplicate top-level roots: currently resources/ and storage/.
    scan_roots: set[str] = set()
    for namespace in namespaces.values():
        relative_path = namespace["path"]
        root_directory = relative_path.split("/", 1)[0]
        scan_roots.add(os.path.join(storage_path, root_directory))
    # Collect remaining files under these roots without recounting known paths.
    for root in sorted(scan_roots):
        unknown_files, unknown_errors = _filestore_audit_scan_directory(
            root,
            "UNKNOWN",
            ignored_paths=known_paths,
        )
        files.extend(unknown_files)
        errors.extend(unknown_errors)

    # Keep report order stable regardless of filesystem traversal order.
    files.sort(key=lambda item: item["path"])
    errors.sort(key=lambda item: item["path"])
    return files, errors


def _filestore_audit_write_csv(
    csv_path: str, fieldnames: list[str], rows: list[dict[str, Any]]
) -> None:
    """Write report rows to a UTF-8 CSV file with the specified column order."""
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _filestore_audit_namespace_summary(
    storage_path: str, files: list[dict[str, Any]], total_size: int
) -> list[dict[str, Any]]:
    """Group inventory files by namespace and calculate each namespace summary."""
    # Include empty namespaces and a bucket for unmatched files.
    namespace_paths: dict[str, str] = {}
    for name, namespace in _filestore_audit_namespaces().items():
        namespace_paths[name] = namespace["path"]
    namespace_paths["UNKNOWN"] = ""
    files_by_namespace: dict[str, list[dict[str, Any]]] = {}
    for name in namespace_paths:
        files_by_namespace[name] = []
    for item in files:
        files_by_namespace[item["namespace"]].append(item)

    rows: list[dict[str, Any]] = []
    # Reuse the reference calculation with each namespace as its scope.
    for name, relative_path in namespace_paths.items():
        namespace_files = files_by_namespace[name]
        namespace_size = 0
        for item in namespace_files:
            namespace_size += item["size_bytes"]
        percentage = namespace_size / total_size * 100 if total_size else 0
        rows.append(
            {
                "namespace": name,
                "path": (
                    os.path.join(storage_path, relative_path)
                    if relative_path
                    else storage_path
                ),
                "file_count": len(namespace_files),
                "size_bytes": namespace_size,
                "size_human": localized_filesize(namespace_size),
                "percentage_of_filestore": f"{percentage:.2f}",
                **_filestore_audit_database_summary(
                    namespace_files, namespace_size
                ),
            }
        )

    return sorted(rows, key=lambda row: (-row["size_bytes"], row["namespace"]))
