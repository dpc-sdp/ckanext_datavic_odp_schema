import logging

import ckan.model as model
import ckan.logic as logic
import ckan.plugins.toolkit as tk
import click
from sqlalchemy.exc import SQLAlchemyError

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
