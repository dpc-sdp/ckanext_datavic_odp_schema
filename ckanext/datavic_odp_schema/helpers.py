from __future__ import annotations

import logging
import math

from datetime import datetime
from dateutil.parser import ParserError, parse as parse_date
from typing import Any, Optional

import ckan.model as model
import ckan.plugins.toolkit as tk


log = logging.getLogger(__name__)


def group_resources_by_temporal_range(
    resource_list: list[dict[str, Any]]
) -> list[list[dict[str, Any]]]:
    """Group resources by period_start/period_end dates for a historical
    feature."""

    def parse_date(date_str: str | None) -> datetime:
        return (
            datetime.strptime(date_str, "%Y-%m-%d")
            if date_str else datetime.min
        )

    grouped_resources: dict[
        tuple[datetime], list[dict[str, Any]]
    ] = {}

    for resource in resource_list:
        end_date = parse_date(resource.get("period_end"))

        grouped_resources.setdefault((end_date,), [])
        grouped_resources[(end_date,)].append(resource)

    sorted_grouped_resources = dict(
        sorted(
            grouped_resources.items(),
            reverse=True,
            key=lambda x: x[0],
        )
    )

    return [res_group for res_group in sorted_grouped_resources.values()]


def ungroup_temporal_resources(
    resource_groups: list[list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    return [
        resource for res_group in resource_groups for resource in res_group
    ]


def is_historical() -> bool:
    return tk.get_endpoint()[1] == "historical"


def date_str_to_timestamp(date: str) -> Optional[int]:
    """Parses date string and return it as a timestamp integer"""
    try:
        date_obj: datetime = parse_date(date)
    except (ParserError, TypeError) as e:
        return log.error("Error parsing date from %s", date)

    return int(date_obj.timestamp())


def is_other_license(pkg_dict: dict[str, Any]) -> bool:
    return pkg_dict.get("license_id") in ["other", "other-open"]


def category_list(self) -> list[dict[str, Any]]:
    group_list = []
    for group in model.Group.all('group'):
        group_list.append({'value': group.id, 'label': group.title})
    return group_list


def localized_filesize(size_bytes: int) -> str:
    """Returns a localized unicode representation of a number in bytes, MB
    etc.

    It's  similar  to  CKAN's  original `localised_filesize`,  but  uses  MB/KB
    instead of MiB/KiB.  Additionally, it rounds up to 1.0KB  any value that is
    smaller than 1000.
    """

    if isinstance(size_bytes, str) and not size_bytes.isdecimal():
        return size_bytes

    size_bytes = int(size_bytes)

    if size_bytes < 1:
        return ""

    size_name = ("bytes", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(float(size_bytes) / p, 1)

    return f"{s} {size_name[i]}"
