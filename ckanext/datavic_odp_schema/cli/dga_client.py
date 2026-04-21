"""DGA (data.gov.au) CKAN API client.

Wraps ``ckanapi.RemoteCKAN`` for organisation and package queries, plus
``requests``-based helpers for file downloads and HEAD size checks.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Generator, Iterator

import ckanapi
import requests

log = logging.getLogger(__name__)

DGA_BASE_URL = "https://data.gov.au/data"
_CHUNK_SIZE = 1024 * 256  # 256 KB
_DOWNLOAD_TIMEOUT = 60  # seconds


def get_dga_client() -> ckanapi.RemoteCKAN:
    """Return a read-only RemoteCKAN client pointed at data.gov.au."""
    return ckanapi.RemoteCKAN(DGA_BASE_URL, get_only=True)


def org_show(client: ckanapi.RemoteCKAN, slug: str) -> dict:
    """Fetch an organisation from DGA by slug.

    Raises ``ckanapi.NotFound`` if the org does not exist.
    """
    return client.action.organization_show(id=slug, include_datasets=False)


def iter_org_packages(
    client: ckanapi.RemoteCKAN, org_slug: str, batch_size: int = 1000
) -> Iterator[dict]:
    """Yield all public dataset dicts for a DGA org, paginated.

    Uses ``package_search`` (which returns full package dicts including
    ``resources``, ``tags``, ``extras`` — no per-dataset ``package_show``
    call needed).
    """
    start = 0
    while True:
        result = client.action.package_search(
            fq=f"organization:{org_slug}",
            rows=batch_size,
            start=start,
            include_private=False,
        )

        packages = result.get("results", [])
        if not packages:
            break
        yield from packages
        start += len(packages)
        if start >= result.get("count", 0):
            break


def head_size(url: str) -> int | None:
    """Return Content-Length from a HEAD request, or None if unavailable."""
    try:
        resp = requests.head(url, allow_redirects=True, timeout=_DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
        length = resp.headers.get("Content-Length")
        return int(length) if length is not None else None
    except Exception as exc:
        log.debug("HEAD %s failed: %s", url, exc)
        return None


def download_file(url: str, dest_path: str, max_bytes: int) -> int:
    """Stream-download ``url`` to ``dest_path``.

    Returns the number of bytes written.

    Raises ``FileTooLargeError`` if the download exceeds ``max_bytes``
    mid-stream (file is left partially written — callers should clean up).
    """
    total = 0
    with requests.get(url, stream=True, timeout=_DOWNLOAD_TIMEOUT) as resp:
        resp.raise_for_status()
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise FileTooLargeError(
                        f"Download exceeded {max_bytes} bytes at {total} bytes"
                    )
                fh.write(chunk)
    return total


class FileTooLargeError(Exception):
    """Raised when a resource download exceeds the configured size cap."""
