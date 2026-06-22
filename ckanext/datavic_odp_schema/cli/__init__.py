import logging

import click
from ckan.plugins.toolkit import enqueue_job
from ckanext.datavic_odp_schema import jobs

from . import detached_export
from . import maintain
from . import migrate_from_dga
from . import reconcile
from . import sync_from_dd

__all__ = [
    "datavic_odp",
]

log = logging.getLogger(__name__)


@click.group()
def datavic_odp():
    """datavic odp management commands."""
    pass


@datavic_odp.command("ckan-job-worker-monitor")
def ckan_worker_job_monitor():
    try:
        enqueue_job(jobs.ckan_worker_job_monitor, title="CKAN job worker monitor")
        click.secho(u"CKAN job worker monitor added to worker queue", fg=u"green")
    except Exception as e:
        log.error(e)


datavic_odp.add_command(maintain.maintain)
datavic_odp.add_command(migrate_from_dga.migrate_from_data_gov_au)
datavic_odp.add_command(reconcile.reconcile_datasets)
datavic_odp.add_command(detached_export.export_detached_syndicated_datasets)
datavic_odp.add_command(sync_from_dd.sync_syndicated_fields)
