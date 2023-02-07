import re
import logging
import time
import calendar

import ckan.plugins.toolkit as tk


log = logging.getLogger(__name__)


def historical_resources_list(resource_list):
    sorted_resource_list = {}
    i = 0
    for resource in resource_list:
        i += 1
        if (
            resource.get("period_start") is not None
            and resource.get("period_start") != "None"
            and resource.get("period_start") != ""
        ):
            key = _parse_date(resource.get("period_start")[:10]) or "9999999999" + str(
                i
            )
        else:
            key = "9999999999" + str(i)
        resource["key"] = key
        sorted_resource_list[key] = resource

    list = sorted(
        sorted_resource_list.values(),
        key=lambda item: int(item.get("key")),
        reverse=True,
    )

    return list


def historical_resources_range(resource_list):
    range_from = ""
    from_ts = None
    range_to = ""
    to_ts = None
    for resource in resource_list:
        if (
            resource.get("period_start") is not None
            and resource.get("period_start") != "None"
            and resource.get("period_start") != ""
        ):
            ts = _parse_date(resource.get("period_start")[:10])
            if ts and (from_ts is None or ts < from_ts):
                from_ts = ts
                range_from = resource.get("period_start")[:10]
        if (
            resource.get("period_end") is not None
            and resource.get("period_end") != "None"
            and resource.get("period_end") != ""
        ):
            ts = _parse_date(resource.get("period_end")[:10])
            if ts and (to_ts is None or ts > to_ts):
                to_ts = ts
                range_to = resource.get("period_end")[:10]

    pattern = "^(\d{4})-(\d{2})-(\d{2})$"

    if range_from and re.match(pattern, range_from):
        range_from = re.sub(pattern, r"\3/\2/\1", range_from)
    if range_to and re.match(pattern, range_to):
        range_to = re.sub(pattern, r"\3/\2/\1", range_to)

    if range_from != "" and range_to != "":
        return range_from + " to " + range_to
    elif range_from != "" or range_to != "":
        return range_from + range_to
    else:
        return None


def is_historical():
    if tk.g.action == "historical":
        return True


def _parse_date(date_str):
    try:
        return calendar.timegm(time.strptime(date_str, "%Y-%m-%d"))
    except Exception as e:
        log.error(e)
        return None


def is_other_license(pkg):
    if pkg.get("license_id") in ["other", "other-open"]:
        return True
    return False
