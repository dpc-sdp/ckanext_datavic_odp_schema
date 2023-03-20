import logging

import click
from ckan.plugins.toolkit import enqueue_job
from ckanext.datavic_odp_schema import jobs

from . import maintain

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


def get_commands():
    return [datavic_odp]
