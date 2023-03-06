import logging

import click

from ckan.plugins.toolkit import enqueue_job

from ckanext.datavic_odp_schema import jobs


log = logging.getLogger(__name__)


@click.command("ckan-job-worker-monitor")
def ckan_worker_job_monitor():
    try:
        enqueue_job(jobs.ckan_worker_job_monitor, title="CKAN job worker monitor")
        click.secho("CKAN job worker monitor added to worker queue", fg="green")
    except Exception as e:
        log.error(e)


def get_commands():
    return [ckan_worker_job_monitor]
