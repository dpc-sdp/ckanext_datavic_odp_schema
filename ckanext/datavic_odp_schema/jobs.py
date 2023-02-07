import os
import logging
from typing import Optional

import requests


log = logging.getLogger(__name__)


def ckan_worker_job_monitor() -> None:
    monitor_url: Optional[str] = os.environ.get("MONITOR_URL_JOBWORKER")

    if not monitor_url:
        return log.error(
            "The env variable MONITOR_URL_JOBWORKER is not set for CKAN worker job monitor"
        )

    try:
        log.info("Sending notification for CKAN worker job monitor")
        requests.get(monitor_url, timeout=10)
    except requests.RequestException as e:
        log.error(
            "Failed to send CKAN worker job monitor notification to %s", monitor_url
        )
        log.error(str(e))

    log.info("Successfully sent notification for CKAN worker job monitor")
