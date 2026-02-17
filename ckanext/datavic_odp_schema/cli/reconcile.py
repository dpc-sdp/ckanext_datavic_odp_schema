"""DV ↔ DD dataset reconciliation.

Compares local Data Vic (DV) datasets against the Data Directory (DD) as the
single source of truth.  Datasets that exist on DV but are not actively
published on DD are classified and optionally purged.

Usage (inside the CKAN container)::

    # Dry-run — classify and generate CSV, no changes
    ckan datavic-odp reconcile-datasets

    # Execute purge of orphans and DD-not-eligible datasets
    ckan datavic-odp reconcile-datasets --purge
"""

from __future__ import annotations

import csv
import datetime
import logging
import os
import sys
from typing import Any

import click
import requests
from sqlalchemy import or_

import ckan.model as model
import ckan.plugins.toolkit as tk
from ckan.lib.search import clear as search_clear

from ckanext.datastore.backend import get_all_resources_ids_in_datastore

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_CFG_DD_URL = "ckanext.datavic_odp.reconciliation.dd_url"
_CFG_DD_API_KEY = "ckanext.datavic_odp.reconciliation.dd_api_key"


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


# ---------------------------------------------------------------------------
# DD API helpers
# ---------------------------------------------------------------------------

_REQUEST_TIMEOUT = 30  # seconds


def _dd_package_search(
    dd_url: str, dd_api_key: str
) -> tuple[set[str], set[str]]:
    """Fetch all active DD dataset names and IDs via paginated package_search.

    Returns:
        (dd_names, dd_ids) — two sets for fast lookup.
    """
    dd_names: set[str] = set()
    dd_ids: set[str] = set()
    rows = 1000
    start = 0

    while True:
        resp = requests.get(
            f"{dd_url}/api/3/action/package_search",
            params={
                "fq": (
                "+state:active "
                "+extras_workflow_status:published "
                "+extras_organization_visibility:all"
            ),
                "rows": rows,
                "start": start,
                "fl": "id,name",
            },
            headers={"Authorization": dd_api_key},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success"):
            raise click.ClickException(
                f"DD package_search failed: {data.get('error', data)}"
            )

        results = data["result"]["results"]
        if not results:
            break

        for pkg in results:
            dd_names.add(pkg["name"])
            dd_ids.add(pkg["id"])

        start += rows

        click.secho(
            f"  Fetched {start} DD datasets so far "
            f"(total: {data['result']['count']})...",
            fg="blue",
        )
        sys.stdout.flush()

    return dd_names, dd_ids


def _get_extra(pkg: dict[str, Any], key: str) -> str | None:
    """Extract an extra value from a CKAN package dict."""
    for extra in pkg.get("extras", []):
        if extra.get("key") == key:
            return extra.get("value")
    return None


def _is_syndication_eligible(pkg: dict[str, Any]) -> bool:
    """Return True if a DD dataset should be syndicated to DV.

    A dataset is eligible when it is active, public, has
    ``workflow_status=published`` and ``organization_visibility=all``.
    """
    if pkg.get("state") != "active" or pkg.get("private"):
        return False
    wf = _get_extra(pkg, "workflow_status")
    ov = _get_extra(pkg, "organization_visibility")
    return wf == "published" and ov == "all"


def _dd_package_show(
    dd_url: str, dd_api_key: str, id_or_name: str
) -> dict[str, Any] | None:
    """Call DD package_show.
    
    Returns:
        dict: Dataset found on DD.
        None: Dataset definitively not found (404 or unsuccessful response).
    
    Raises:
        requests.RequestException: API error (network, timeout, server error).
            Caller should treat as "uncertain" status.
    """
    resp = requests.get(
        f"{dd_url}/api/3/action/package_show",
        params={"id": id_or_name},
        headers={"Authorization": dd_api_key},
        timeout=_REQUEST_TIMEOUT,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    if data.get("success"):
        return data["result"]
    return None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _classify_datasets(
    dv_datasets: list[tuple[str, str, str, str]],
    dd_names: set[str],
    dd_ids: set[str],
    dd_url: str,
    dd_api_key: str,
) -> list[dict[str, str]]:
    """Classify every DV dataset.

    Returns a list of dicts with keys:
        dv_id, dv_name, dv_state, classification, dd_name, dd_state, action
    """
    results: list[dict[str, str]] = []
    unmatched: list[tuple[str, str, str]] = []

    # Phase 1: batch name match (fast, covers ~95%).
    for dv_id, dv_name, dv_state, dv_owner_org in dv_datasets:
        if dv_name in dd_names:
            results.append(
                _row(dv_id, dv_name, dv_state, dv_owner_org, "matched", dv_name, "active", "keep")
            )
        else:
            unmatched.append((dv_id, dv_name, dv_state, dv_owner_org))

    click.secho(
        f"  Phase 1 — {len(results)} matched by name, "
        f"{len(unmatched)} unmatched.",
        fg="blue",
    )
    sys.stdout.flush()

    # Phase 2: individual API verification for unmatched.
    for i, (dv_id, dv_name, dv_state, dv_owner_org) in enumerate(unmatched, 1):
        if i % 50 == 0:
            click.secho(f"  Phase 2 — verifying {i}/{len(unmatched)}...", fg="blue")
            sys.stdout.flush()

        classification = "uncertain"
        dd_name = ""
        dd_state = ""
        action = "skip"

        # Check by name first.
        try:
            dd_pkg = _dd_package_show(dd_url, dd_api_key, dv_name)
        except Exception as exc:
            # Any error (network, JSON decode, unexpected) — can't
            # determine status, mark uncertain and move on.
            log.warning(
                "DD error checking dataset %s by name: %s", dv_name, exc
            )
            results.append(
                _row(dv_id, dv_name, dv_state, dv_owner_org, classification, dd_name, dd_state, action)
            )
            continue

        if dd_pkg:
            # Found by name — check syndication eligibility.
            dd_name = dd_pkg.get("name", "")
            dd_state = dd_pkg.get("state", "")
            if _is_syndication_eligible(dd_pkg):
                # Active, public, published, visibility=all — keep.
                classification = "matched"
                action = "keep"
            else:
                # Exists on DD but not eligible for syndication
                # (inactive/private/draft/restricted visibility).
                classification = "dd_not_eligible"
                action = "purge"
        else:
            # Not found by name (404) — try by DV dataset ID.
            try:
                dd_pkg_by_id = _dd_package_show(dd_url, dd_api_key, dv_id)
            except Exception as exc:
                # Any error — can't determine status, mark uncertain
                # and move on.
                log.warning(
                    "DD error checking dataset %s by ID: %s", dv_id, exc
                )
                results.append(
                    _row(dv_id, dv_name, dv_state, dv_owner_org, classification, dd_name, dd_state, action)
                )
                continue

            if dd_pkg_by_id:
                # Found by ID — name mismatch, dataset is valid on DD.
                dd_name = dd_pkg_by_id.get("name", "")
                dd_state = dd_pkg_by_id.get("state", "")
                classification = "dd_name_mismatch"
                action = "keep"
            else:
                # Not found by name or ID (both returned 404) — confirmed orphan.
                classification = "orphan"
                action = "purge"

        results.append(
            _row(dv_id, dv_name, dv_state, dv_owner_org, classification, dd_name, dd_state, action)
        )

    return results


def _row(
    dv_id: str,
    dv_name: str,
    dv_state: str,
    dv_owner_org: str,
    classification: str,
    dd_name: str,
    dd_state: str,
    action: str,
) -> dict[str, str]:
    return {
        "dv_id": dv_id,
        "dv_name": dv_name,
        "dv_state": dv_state,
        "dv_owner_org": dv_owner_org,
        "classification": classification,
        "dd_name": dd_name,
        "dd_state": dd_state,
        "action": action,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Purge logic
# ---------------------------------------------------------------------------


def _purge_dataset(dataset_id: str, dataset_name: str) -> None:
    """Purge a single DV dataset via direct SQL DELETE + Solr clear."""

    # 1. Clear from Solr index.
    search_clear(dataset_id)

    # 2. Delete child rows without DB-level CASCADE.
    model.Session.query(model.Resource).filter_by(
        package_id=dataset_id
    ).delete()
    model.Session.query(model.PackageExtra).filter_by(
        package_id=dataset_id
    ).delete()
    model.Session.query(model.PackageTag).filter_by(
        package_id=dataset_id
    ).delete()
    model.Session.query(model.PackageRelationship).filter(
        or_(
            model.PackageRelationship.subject_package_id == dataset_id,
            model.PackageRelationship.object_package_id == dataset_id,
        )
    ).delete(synchronize_session="fetch")
    model.Session.query(model.Member).filter(
        model.Member.table_id == dataset_id,
        model.Member.table_name == "package",
    ).delete()
    model.Session.query(model.PackageMember).filter_by(
        package_id=dataset_id
    ).delete()

    # 3. Delete the package row (triggers CASCADE for resource_view,
    #    user_following_dataset).
    model.Session.query(model.Package).filter_by(id=dataset_id).delete()
    model.Session.commit()


# ---------------------------------------------------------------------------
# CSV report
# ---------------------------------------------------------------------------

_CSV_COLUMNS = [
    "dv_id",
    "dv_name",
    "dv_state",
    "dv_owner_org",
    "classification",
    "dd_name",
    "dd_state",
    "action",
    "timestamp",
]


def _write_csv(rows: list[dict[str, str]], path: str) -> None:
    csv_dir = os.path.dirname(path)
    if csv_dir:
        os.makedirs(csv_dir, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    click.secho(f"  CSV report written to {path}", fg="green")


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------


@click.command("reconcile-datasets")
@click.option(
    "--purge",
    "do_purge",
    is_flag=True,
    default=False,
    help="Execute purge of orphan and DD-not-eligible datasets.  "
    "Without this flag the command runs as a dry-run.",
)
@click.option(
    "--csv-path",
    default=None,
    type=click.Path(),
    help="Path for the CSV audit report.  Defaults to "
    "/app/filestore/purge_reports/dv_reconciliation_<timestamp>.csv",
)
def reconcile_datasets(do_purge: bool, csv_path: str | None) -> None:
    """Reconcile DV datasets against the DD source of truth.

    Dry-run by default — classifies every DV dataset and generates a CSV
    report without making any changes.  Pass --purge to execute.
    """

    mode = "PURGE" if do_purge else "DRY-RUN"
    click.secho(f"=== DV ↔ DD Reconciliation [{mode}] ===\n", fg="cyan", bold=True)
    sys.stdout.flush()

    # ---- Config -----------------------------------------------------------
    dd_url = _dd_url()
    dd_api_key = _dd_api_key()
    click.secho(f"DD URL: {dd_url}", fg="blue")
    sys.stdout.flush()

    # ---- Fetch DD reference set -------------------------------------------
    click.secho("Fetching DD active dataset reference set...", fg="blue")
    sys.stdout.flush()
    dd_names, dd_ids = _dd_package_search(dd_url, dd_api_key)
    click.secho(
        f"  DD reference: {len(dd_names)} active datasets.\n", fg="green"
    )
    sys.stdout.flush()

    # ---- Fetch DV local datasets ------------------------------------------
    click.secho("Fetching DV local datasets...", fg="blue")
    sys.stdout.flush()
    dv_datasets: list[tuple[str, str, str]] = (
        model.Session.query(
            model.Package.id, model.Package.name, model.Package.state, model.Package.owner_org
        )
        .filter(model.Package.type == "dataset")
        .all()
    )
    click.secho(f"  DV local: {len(dv_datasets)} datasets.\n", fg="green")
    sys.stdout.flush()

    # ---- Classify ---------------------------------------------------------
    click.secho("Classifying DV datasets...", fg="blue")
    sys.stdout.flush()
    classified = _classify_datasets(
        dv_datasets, dd_names, dd_ids, dd_url, dd_api_key
    )

    # Tally classifications.
    tallies: dict[str, int] = {}
    for row in classified:
        tallies[row["classification"]] = tallies.get(row["classification"], 0) + 1

    click.secho("\nClassification summary:", fg="cyan", bold=True)
    for cls_name in ("matched", "orphan", "dd_not_eligible", "dd_name_mismatch", "uncertain"):
        count = tallies.get(cls_name, 0)
        colour = "green" if cls_name == "matched" else "yellow" if cls_name in ("dd_name_mismatch", "uncertain") else "red"
        click.secho(f"  {cls_name}: {count}", fg=colour)
    sys.stdout.flush()

    # ---- CSV report -------------------------------------------------------
    if not csv_path:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = (
            f"/app/filestore/purge_reports/dv_reconciliation_{ts}.csv"
        )
    _write_csv(classified, csv_path)

    # ---- Purge (if requested) ---------------------------------------------
    to_purge = [r for r in classified if r["action"] == "purge"]

    if not do_purge:
        click.secho(
            f"\nDry-run complete.  {len(to_purge)} datasets would be purged.  "
            f"Re-run with --purge to execute.\n",
            fg="cyan",
        )
        sys.stdout.flush()

        # Exit with non-zero status when datasets would be purged so the
        # calling shell script can report to the monitoring service.
        if to_purge:
            raise SystemExit(1)
        return

    if not to_purge:
        click.secho("\nNo datasets to purge.\n", fg="green")
        sys.stdout.flush()
        return

    click.secho(f"\nPurging {len(to_purge)} datasets...\n", fg="blue", bold=True)
    sys.stdout.flush()

    purged = 0
    failed = 0

    for row in to_purge:
        dv_id = row["dv_id"]
        dv_name = row["dv_name"]
        classification = row["classification"]
        try:
            click.secho(
                f"  Purging {dv_name} ({classification})", fg="blue"
            )
            sys.stdout.flush()
            _purge_dataset(dv_id, dv_name)
            purged += 1
        except Exception as exc:
            click.secho(f"  ERROR purging {dv_name}: {exc}", fg="red")
            log.error("Failed to purge DV dataset %s (%s): %s", dv_name, dv_id, exc)
            model.Session.rollback()
            failed += 1

    # ---- Post-purge: Solr orphan cleanup ----------------------------------
    click.secho("\nCleaning up Solr orphaned entries...", fg="blue")
    sys.stdout.flush()
    try:
        from ckan.cli.search_index import get_orphans

        orphans = get_orphans()
        for orphan_id in orphans:
            search_clear(orphan_id)
        if orphans:
            click.secho(
                f"  Cleared {len(orphans)} orphaned Solr entries", fg="green"
            )
        else:
            click.secho("  No orphaned Solr entries found", fg="green")
    except Exception as exc:
        click.secho(f"  WARNING: Solr orphan cleanup failed: {exc}", fg="yellow")
        log.warning("Solr orphan cleanup failed: %s", exc)

    # ---- Post-purge: datastore orphan cleanup -----------------------------
    click.secho("Cleaning up orphaned datastore tables...", fg="blue")
    sys.stdout.flush()
    try:
        site_user = tk.get_action("get_site_user")({"ignore_auth": True}, {})
        ds_dropped = 0
        for resid in get_all_resources_ids_in_datastore():
            try:
                tk.get_action("resource_show")(
                    {"user": site_user["name"]}, {"id": resid}
                )
            except (tk.ObjectNotFound, KeyError):
                try:
                    tk.get_action("datastore_delete")(
                        {"user": site_user["name"]},
                        {"resource_id": resid, "force": True},
                    )
                    ds_dropped += 1
                except Exception:
                    pass
        if ds_dropped:
            click.secho(
                f"  Dropped {ds_dropped} orphaned datastore tables",
                fg="green",
            )
        else:
            click.secho("  No orphaned datastore tables found", fg="green")
    except Exception as exc:
        click.secho(
            f"  WARNING: datastore cleanup failed: {exc}", fg="yellow"
        )
        log.warning("Datastore cleanup failed: %s", exc)

    # ---- Summary ----------------------------------------------------------
    click.secho(
        f"\nDone.  {purged} datasets purged, {failed} failed.",
        fg="green" if failed == 0 else "yellow",
    )
    sys.stdout.flush()
