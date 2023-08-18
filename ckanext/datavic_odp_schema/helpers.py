from __future__ import annotations

import logging
from typing import Any, Optional
from datetime import datetime

from dateutil.parser import ParserError, parse as parse_date

import ckan.plugins.toolkit as tk


log = logging.getLogger(__name__)


def historical_resources_list(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resources_history: dict[str, dict[str, Any]] = {}

    for idx, resource in enumerate(resources):
        resource["_key"] = _key = date_str_to_timestamp(
            resource.get("period_start", "")
        ) or int(f"9999999999{idx}")

        resources_history[str(_key)] = resource

    return sorted(resources_history.values(), key=lambda res: res["_key"], reverse=True)


def group_resources_by_temporal_range(
    resource_list: list[dict[str, Any]]
) -> list[list[dict[str, Any]]]:
    """Group resources by period_start/period_end dates for a historical
    feature."""

    def parse_date(date_str: str | None) -> datetime:
        return (
            datetime.strptime(date_str, "%Y-%m-%d") if date_str else datetime.min
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
        return log.error("Eror parsing date from %s", date)

    return int(date_obj.timestamp())


def is_other_license(pkg_dict: dict[str, Any]) -> bool:
    return pkg_dict.get("license_id") in ["other", "other-open"]
