import os
import requests
import logging


log = logging.getLogger(__name__)


def ckan_worker_job_monitor():
    monitor_url = os.environ.get("MONITOR_URL_JOBWORKER")
    try:
        if monitor_url:
            log.info(f"Sending notification for CKAN worker job monitor")
            requests.get(monitor_url, timeout=10)
            log.info(f"Successfully sent notification for CKAN worker job monitor")
        else:
            log.error(
                f"The env variable MONITOR_URL_JOBWORKER is not set for CKAN worker job monitor"
            )
    except requests.RequestException as e:
        log.error(
            f"Failed to send CKAN worker job monitor notification to {monitor_url}"
        )
        log.error(str(e))
