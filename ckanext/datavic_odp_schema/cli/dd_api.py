"""Shared DD (Data Directory) API helpers for reconciliation and sync.

Used by reconcile, sync_from_dd, and detached_export. Reads config from
ckanext.datavic_odp.reconciliation.dd_url and dd_api_key (e.g. DD_RECONCILIATION_URL,
DD_RECONCILIATION_API_KEY).
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import click
import requests

import ckan.plugins.toolkit as tk

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CFG_DD_URL = "ckanext.datavic_odp.reconciliation.dd_url"
_CFG_DD_API_KEY = "ckanext.datavic_odp.reconciliation.dd_api_key"
_CFG_API_TOKEN_HEADER = "apitoken_header_name"
_DEFAULT_API_TOKEN_HEADER = "X-CKAN-API-Key"

REQUEST_TIMEOUT = 30  # seconds


def _dd_url() -> str:
    url = tk.config.get(_CFG_DD_URL, "").strip().rstrip("/")
    if not url:
        raise click.ClickException(
            f"DD URL not configured.  Set {_CFG_DD_URL} in ckan.ini "
            f"or the corresponding environment variable."
        )
    return url


def _dd_api_key() -> str:
    key = tk.config.get(_CFG_DD_API_KEY, "").strip()
    if not key:
        raise click.ClickException(
            f"DD API key not configured.  Set {_CFG_DD_API_KEY} in ckan.ini "
            f"or the corresponding environment variable."
        )
    return key


def _dd_auth_headers(dd_api_key: str) -> dict[str, str]:
    header_name = (
        tk.config.get(_CFG_API_TOKEN_HEADER, "").strip()
        or _DEFAULT_API_TOKEN_HEADER
    )
    return {header_name: dd_api_key}


def _get_extra(pkg: dict[str, Any], key: str) -> str | None:
    """Extract an extra value from a CKAN package dict.

    Also checks top-level key (e.g. package_show may flatten extras).
    """
    val = pkg.get(key)
    if val is not None and val != "":
        return str(val) if not isinstance(val, str) else val
    for extra in pkg.get("extras", []):
        if extra.get("key") == key:
            v = extra.get("value")
            return str(v) if v is not None else None
    return None


# ---------------------------------------------------------------------------
# DD API
# ---------------------------------------------------------------------------

_SEARCH_FQ = (
    "+state:active "
    "+extras_workflow_status:published "
    "+extras_organization_visibility:all"
)
_PAGE_SIZE = 1000
_MAX_PAGE_WORKERS = 8


def _fetch_dd_search_page(
    dd_url: str,
    dd_api_key: str,
    start: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Fetch one page of DD package_search. Returns (start, results)."""
    resp = requests.get(
        f"{dd_url}/api/3/action/package_search",
        params={
            "fq": _SEARCH_FQ,
            "rows": _PAGE_SIZE,
            "start": start,
        },
        headers=_dd_auth_headers(dd_api_key),
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise click.ClickException(
            f"DD package_search failed: {data.get('error', data)}"
        )
    results = data["result"].get("results") or []
    return (start, results)


def fetch_dd_active_packages(
    dd_url: str,
    dd_api_key: str,
    progress_callback: None | Any = None,
) -> list[dict[str, Any]]:
    """Fetch all active DD dataset package dicts via paginated package_search.

    Same fq as reconcile: active, workflow_status=published, organization_visibility=all.
    First page is fetched to get total count; remaining pages are fetched in parallel.
    """
    # First page: get count and initial results (API returns "count" in result)
    resp = requests.get(
        f"{dd_url}/api/3/action/package_search",
        params={"fq": _SEARCH_FQ, "rows": _PAGE_SIZE, "start": 0},
        headers=_dd_auth_headers(dd_api_key),
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise click.ClickException(
            f"DD package_search failed: {data.get('error', data)}"
        )
    result = data["result"]
    packages = list(result.get("results") or [])
    total_count = result.get("count", len(packages))

    if total_count <= _PAGE_SIZE:
        if progress_callback:
            progress_callback(len(packages), total_count)
        else:
            click.secho(
                f"  Fetched {len(packages)} DD datasets (total: {total_count})...",
                fg="blue",
            )
            sys.stdout.flush()
        return packages

    # Remaining page offsets: 1000, 2000, ...
    page_starts = list(range(_PAGE_SIZE, total_count, _PAGE_SIZE))
    page_results: dict[int, list] = {}

    with ThreadPoolExecutor(max_workers=min(_MAX_PAGE_WORKERS, len(page_starts))) as executor:
        future_to_start = {}
        for s in page_starts:
            future = executor.submit(_fetch_dd_search_page, dd_url, dd_api_key, s)
            future_to_start[future] = s
        for future in as_completed(future_to_start):
            s, results = future.result()
            page_results[s] = results
            n_so_far = len(packages) + sum(len(r) for r in page_results.values())
            if progress_callback:
                progress_callback(n_so_far, total_count)
            else:
                click.secho(
                    f"  Fetched {n_so_far}/{total_count} DD datasets...",
                    fg="blue",
                )
                sys.stdout.flush()

    for s in sorted(page_results):
        packages.extend(page_results[s])

    return packages


def dd_package_show(
    dd_url: str, dd_api_key: str, id_or_name: str
) -> dict[str, Any] | None:
    """Call DD package_show.

    Returns:
        dict: Dataset found on DD.
        None: Dataset not found (404 or unsuccessful response).

    Raises:
        requests.RequestException: API error (network, timeout, server error).
    """
    resp = requests.get(
        f"{dd_url}/api/3/action/package_show",
        params={"id": id_or_name},
        headers=_dd_auth_headers(dd_api_key),
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    if data.get("success"):
        return data["result"]
    return None
