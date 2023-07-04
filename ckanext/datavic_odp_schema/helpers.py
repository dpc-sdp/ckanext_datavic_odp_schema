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
