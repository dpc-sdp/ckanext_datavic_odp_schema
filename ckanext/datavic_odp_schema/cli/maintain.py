import logging

import ckan.model as model
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
