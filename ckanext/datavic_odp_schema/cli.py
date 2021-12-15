import click
import logging

from ckan.plugins.toolkit import enqueue_job
from ckanext.datavic_odp_schema.jobs import jobs

log = logging.getLogger(__name__)

@click.command(u"ckan-job-worker-monitor")
def ckan_worker_job_monitor():
    try:
        enqueue_job(jobs.ckan_worker_job_monitor, title='CKAN job worker monitor')
        click.secho(u"CKAN job worker monitor added to worker queue", fg=u"green")
    except Exception as e:
        log.error(e)


def get_commands():
    return [ckan_worker_job_monitor]