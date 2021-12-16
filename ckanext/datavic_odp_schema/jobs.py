import os
import requests
import logging

log = logging.getLogger(__name__)
monitor_url = os.environ.get('MONITOR_URL_JOBWORKER')

def ckan_worker_job_monitor():
    try:
        log.info(f'Sending monitor notification to {monitor_url} for CKAN worker job monitor')
        requests.get(monitor_url, timeout=10)
        log.info(f'Successfully sent monitor notification to {monitor_url} for CKAN worker job monitor')
    except requests.RequestException as e:
        log.error(f'Failed to send monitor notification to {monitor_url} for CKAN worker job monitor')
        log.error(str(e))