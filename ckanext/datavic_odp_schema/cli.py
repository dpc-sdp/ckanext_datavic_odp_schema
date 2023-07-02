import logging
from typing import List

import click

from ckan.plugins.toolkit import enqueue_job
import ckan.model as model
import ckan.logic as logic

from ckanext.datavic_odp_schema import jobs


log = logging.getLogger(__name__)


@click.command("ckan-job-worker-monitor")
def ckan_worker_job_monitor():
    try:
        enqueue_job(jobs.ckan_worker_job_monitor, title="CKAN job worker monitor")
        click.secho("CKAN job worker monitor added to worker queue", fg="green")
    except Exception as e:
        log.error(e)


@click.command(u"purge-deleted-datasets", short_help=u"Purge deleted datasets")
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
            click.secho(f"{dataset[0]} '{dataset[1]}' purged", fg="yellow")

        click.secho("Done.", fg="green")


def get_commands():
    return [ckan_worker_job_monitor, purge_deleted_datasets]
