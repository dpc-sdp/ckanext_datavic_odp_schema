from __future__ import annotations

import logging

import ckan.model as model
from ckan.model import Resource, ResourceView
import ckan.logic as logic
import ckan.plugins.toolkit as tk
import click
from sqlalchemy.exc import SQLAlchemyError

import tqdm

log = logging.getLogger(__name__)


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
        click.secho(f"ckanext-harvest table removed successfully", fg="green")
    except SQLAlchemyError:
        click.secho(f"DB Error: Failed to drop ckanext-harvest tables", fg="red")
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
        click.secho(
            "No resources have been found",
            fg="green"
        )
        return click.secho(
            "NOTE: `datatables_view` works only with resources uploaded to datastore",
            fg="green"
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
    search = tk.get_action("datastore_search")
    ctx = {"ignore_auth": True}
    data_dict = {
        "resource_id": resource_id,
        "limit": 0,
        "include_total": False,
    }
    fields = [field for field in search(ctx, data_dict)["fields"]]
    return [f["id"] for f in fields]


def _delete_recline_views(res_views: list[ResourceView]):
    for view in res_views:
        if view.view_type != "recline_view":
            continue
        view.delete()
    model.repo.commit()


@maintain.command(u"purge-deleted-datasets", short_help=u"Purge deleted datasets by type")
@click.argument(u"type")
def purge_deleted_datasets(type: str):
    """Removes deleted datasets of certain type from db entirely

    Args:
        type (str): type of datasets to be purged
    """
    log.info(f"Searching for deleted datasets of <{type}> type...")

    datasets = model.Session.query(model.Package.id, model.Package.title)\
        .filter(model.Package.type == type)\
        .filter(model.Package.state == u"deleted").all()

    if not datasets:
        click.secho(f"No datasets of <{type}> type were founded", fg="green")
    else:
        click.secho(
            f"{len(datasets)} deleted datasets of <{type}> type were founded.",
            fg="green"
        )
        for dataset in datasets:
            site_user = logic.get_action(u'get_site_user')({u'ignore_auth': True}, {})
            context = {u'user': site_user[u'name'], u'ignore_auth': True}
            logic.get_action(u'dataset_purge')(context, {u'id': dataset[0]})
            click.secho(f"{dataset[0]} '{dataset[1]}' - purged", fg="yellow")

        click.secho("Done.", fg="green")


@maintain.command("purge-empty-orgs")
def purge_empty_organizations():
    """Purge organizations without any datasets"""
    result = tk.get_action("organization_list")(
        {"ignore_auth": True},
        {"all_fields": True}
    )

    empty_orgs = [org for org in result if org["package_count"] == 0]

    if not empty_orgs:
        return click.secho("No empty organization.", fg="green")

    click.secho(f"Found {len(empty_orgs)} empty organization(s). Purging...")

    for org_dict in empty_orgs:
        tk.get_action("organization_purge")(
            {"ignore_auth": True},
            {"id": org_dict["id"]}
        )
