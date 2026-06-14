"""Backfill fields for DV datasets that are not syndicated from DD.

Checks each local Data Vic dataset against the Data Directory (DD). 
Datasets found on DD are ignored. Datasets not found on DD 
can have required values backfilled.

Dry-run by default. Pass ``--execute`` to write changes.
"""

from __future__ import annotations

import csv
import datetime
import logging
import os
import sys
from typing import Any, Iterator

import click

import ckan.model as model
import ckan.plugins.toolkit as tk

from . import dd_api

log = logging.getLogger(__name__)

DEFAULT_DATA_OWNER = "https://www.data.vic.gov.au/contact-us"
DEFAULT_REPORT_DIR = "/app/filestore/backfill_non_syndicated_reports"
DEFAULT_BATCH_SIZE = 500

_REPORT_COLUMNS = [
    "dv_id",
    "dv_name",
    "dv_state",
    "action",
    "data_owner",
    "data_owner_action",
    "contact_point",
    "contact_point_action",
    "error",
]


# Load DV datasets in small ordered chunks.
def _iter_dataset_rows(batch_size: int) -> Iterator[tuple[str, str, str, str]]:
    last_id = ""

    while True:
        rows = (
            model.Session.query(
                model.Package.id,
                model.Package.name,
                model.Package.state,
                model.Package.owner_org,
                model.Group.name,
                model.Group.title,
            )
            .outerjoin(model.Group, model.Package.owner_org == model.Group.id)
            .filter(model.Package.type == "dataset")
            .filter(model.Package.id > last_id)
            .order_by(model.Package.id)
            .limit(batch_size)
            .all()
        )
        if not rows:
            return

        for row in rows:
            last_id = row[0]
            org_label = row[5] or row[4] or row[3] or "unknown"
            yield (row[0], row[1], row[2], org_label)


# Build the required contact_point value from the owning organisation label.
def _contact_point_for_org(org_label: str) -> str:
    return f"organization: {org_label}"


# Convert the DD package list into sets.
def _dd_reference_sets(
    dd_packages: list[dict[str, Any]],
) -> tuple[set[str], set[str], set[str]]:
    """Return DD package names, IDs, and syndicated DV IDs."""
    dd_names = {pkg["name"] for pkg in dd_packages if pkg.get("name")}
    dd_ids = {pkg["id"] for pkg in dd_packages if pkg.get("id")}
    dd_syndicated_ids = {
        sid
        for pkg in dd_packages
        for sid in [dd_api._get_extra(pkg, "syndicated_id")]
        if sid
    }
    return dd_names, dd_ids, dd_syndicated_ids


# Decide whether one package_extra field should be populated. By default
# existing non-empty values are preserved; whitespace-only values count as empty.
def _extra_action(
    session: Any,
    package_id: str,
    key: str,
    value: str,
    override_existing: bool,
) -> str:
    """Return inserted/updated/unchanged/skipped_existing for one extra."""
    existing = (
        session.query(model.PackageExtra)
        .filter_by(package_id=package_id, key=key)
        .first()
    )
    if existing:
        current = existing.value or ""
        if not override_existing and current.strip():
            return "skipped_existing"
        if existing.value == value and existing.state == "active":
            return "unchanged"
        return "updated"

    return "inserted"


# Collapse per-field results into one dataset-level report action.
def _row_action(field_actions: list[str], dry_run: bool) -> str:
    if any(action in ("inserted", "updated") for action in field_actions):
        return "would_backfill" if dry_run else "updated"
    if all(action == "skipped_existing" for action in field_actions):
        return "skipped_existing"
    return "unchanged"


# Apply field updates through CKAN actions so validators, activity, search, and
# extension hooks run as they would for a normal dataset update.
def _package_update_fields(
    context: dict[str, Any],
    package_id: str,
    values: dict[str, str],
) -> None:
    pkg = tk.get_action("package_show")(context, {"id": package_id})
    pkg.update(values)
    tk.get_action("package_update")(context, pkg)


# Check whether a DV dataset appears in the pre-fetched DD reference set.
def _dd_dataset_match_from_reference(
    dv_id: str,
    dv_name: str,
    dd_names: set[str],
    dd_ids: set[str],
    dd_syndicated_ids: set[str],
) -> str:
    """Return the DD reference field that matched this DV dataset, or empty string."""
    if dv_name in dd_names:
        return "name"
    if dv_id in dd_ids:
        return "id"
    if dv_id in dd_syndicated_ids:
        return "syndicated_id"
    return ""


# Resolve the CSV report destination.
def _report_path(path: str | None) -> str:
    if path:
        return path
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(
        DEFAULT_REPORT_DIR.rstrip("/"),
        f"backfill_non_syndicated_fields_{ts}.csv",
    )


@click.command("backfill-non-syndicated-fields")
@click.option(
    "--execute",
    "do_execute",
    is_flag=True,
    default=False,
    help="Write backfilled values. Without this flag the command runs as a dry-run.",
)
@click.option(
    "--batch-size",
    default=DEFAULT_BATCH_SIZE,
    show_default=True,
    type=click.IntRange(min=1),
    help="Number of DV dataset rows to load from the database per batch.",
)
@click.option(
    "--report-path",
    default=None,
    type=click.Path(),
    help=(
        "Path for the affected-datasets CSV report. Defaults to "
        "<DEFAULT_REPORT_DIR>/backfill_non_syndicated_fields_<timestamp>.csv."
    ),
)
@click.option(
    "--override-existing",
    is_flag=True,
    default=False,
    help=(
        "Overwrite existing non-empty values. By default only missing or "
        "whitespace-only values are populated."
    ),
)
def backfill_non_syndicated_fields(
    do_execute: bool,
    batch_size: int,
    report_path: str | None,
    override_existing: bool,
) -> None:
    """Backfill custodian extras for DV datasets not syndicated from DD.

    DD connection details are read via ``dd_api.py`` from
    ``ckanext.datavic_odp.reconciliation.dd_url`` and
    ``ckanext.datavic_odp.reconciliation.dd_api_key``.
    """
    mode = "EXECUTE" if do_execute else "DRY-RUN"
    click.secho(
        f"=== Backfill non-syndicated dataset fields [{mode}] ===\n",
        fg="cyan",
        bold=True,
    )
    click.secho(
        "Existing values: "
        + (
            "overwrite non-empty values"
            if override_existing
            else "populate empty values only"
        ),
        fg="blue",
    )
    sys.stdout.flush()

    # Read DD connection settings.
    dd_url = dd_api._dd_url()
    dd_api_key = dd_api._dd_api_key()
    click.secho(f"DD URL: {dd_url}\n", fg="blue")
    sys.stdout.flush()

    # Fetch DD once, then classify DV datasets locally.
    click.secho("Fetching DD active dataset reference set...", fg="blue")
    sys.stdout.flush()
    dd_packages = dd_api.fetch_dd_active_packages(dd_url, dd_api_key)
    dd_names, dd_ids, dd_syndicated_ids = _dd_reference_sets(dd_packages)
    click.secho(
        f"  DD reference: {len(dd_names)} active datasets; "
        f"{len(dd_syndicated_ids)} with syndicated_id.\n",
        fg="green",
    )
    sys.stdout.flush()

    # Use the site user in execute mode so CKAN records updates through the
    # normal action pipeline.
    action_context = None
    if do_execute:
        site_user = tk.get_action("get_site_user")({"ignore_auth": True}, {})
        action_context = {"ignore_auth": True, "user": site_user["name"]}

    report_path = _report_path(report_path)
    report_dir = os.path.dirname(report_path)
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)

    # Keep separate counters for scanned datasets, DD matches, affected
    # datasets, write outcomes, and CSV rows.
    counters = {
        "checked": 0,
        "available": 0,
        "missing": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped_existing": 0,
        "errors": 0,
        "reported": 0,
    }

    with open(report_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_REPORT_COLUMNS)
        writer.writeheader()

        # Stream DV datasets, skip anything represented in DD, and report only
        # rows that this command would backfill or has attempted to backfill.
        for dv_id, dv_name, dv_state, org_label in _iter_dataset_rows(batch_size):
            counters["checked"] += 1
            if counters["checked"] % batch_size == 0:
                click.secho(
                    f"  Checked {counters['checked']} DV datasets...",
                    fg="blue",
                )
                sys.stdout.flush()

            row = {
                "dv_id": dv_id,
                "dv_name": dv_name,
                "dv_state": dv_state,
                "action": "",
                "data_owner": DEFAULT_DATA_OWNER,
                "data_owner_action": "",
                "contact_point": _contact_point_for_org(org_label),
                "contact_point_action": "",
                "error": "",
            }

            matched_by = _dd_dataset_match_from_reference(
                dv_id,
                dv_name,
                dd_names,
                dd_ids,
                dd_syndicated_ids,
            )

            if matched_by:
                counters["available"] += 1
                continue

            # Missing from DD means the dataset is non-syndicated for this
            # command and should appear in the affected-datasets report.
            counters["missing"] += 1

            # Dry-run uses the same write decision logic without mutating rows.
            if not do_execute:
                data_owner_result = _extra_action(
                    model.Session,
                    dv_id,
                    "data_owner",
                    row["data_owner"],
                    override_existing,
                )
                contact_point_result = _extra_action(
                    model.Session,
                    dv_id,
                    "contact_point",
                    row["contact_point"],
                    override_existing,
                )
                row["data_owner_action"] = data_owner_result
                row["contact_point_action"] = contact_point_result
                row["action"] = _row_action(
                    [data_owner_result, contact_point_result],
                    dry_run=True,
                )
                if row["action"] == "would_backfill":
                    writer.writerow(row)
                    counters["reported"] += 1
                continue

            # Execute mode updates through package_update. Only fields that
            # need to be inserted or changed are sent to CKAN.
            try:
                data_owner_result = _extra_action(
                    model.Session,
                    dv_id,
                    "data_owner",
                    row["data_owner"],
                    override_existing,
                )
                contact_point_result = _extra_action(
                    model.Session,
                    dv_id,
                    "contact_point",
                    row["contact_point"],
                    override_existing,
                )
                row["data_owner_action"] = data_owner_result
                row["contact_point_action"] = contact_point_result
                row["action"] = _row_action(
                    [data_owner_result, contact_point_result],
                    dry_run=False,
                )

                values_to_update = {}
                if data_owner_result in ("inserted", "updated"):
                    values_to_update["data_owner"] = row["data_owner"]
                if contact_point_result in ("inserted", "updated"):
                    values_to_update["contact_point"] = row["contact_point"]

                if not values_to_update:
                    if row["action"] == "skipped_existing":
                        counters["skipped_existing"] += 1
                    else:
                        counters["unchanged"] += 1
                    continue

                if action_context is None:
                    raise click.ClickException("Missing CKAN action context.")
                _package_update_fields(action_context, dv_id, values_to_update)

                if row["action"] == "skipped_existing":
                    counters["skipped_existing"] += 1
                elif row["action"] == "unchanged":
                    counters["unchanged"] += 1
                else:
                    counters["updated"] += 1
            except Exception as exc:
                counters["errors"] += 1
                model.Session.rollback()
                row["action"] = "error"
                row["error"] = str(exc)
                log.error(
                    "Failed to backfill fields for DV dataset %s (%s): %s",
                    dv_name,
                    dv_id,
                    exc,
                )
                click.secho(f"  ERROR updating {dv_name}: {exc}", fg="red")
                sys.stdout.flush()

            writer.writerow(row)
            counters["reported"] += 1

    # Print a compact operational summary after all rows have been scanned.
    click.secho("\n--- Summary ---", fg="cyan", bold=True)
    click.secho(f"  Checked:      {counters['checked']}", fg="blue")
    click.secho(f"  DD available: {counters['available']}", fg="green")
    click.secho(f"  DD missing:   {counters['missing']}", fg="yellow")
    if do_execute:
        click.secho(f"  Updated:      {counters['updated']}", fg="green")
        click.secho(f"  Unchanged:    {counters['unchanged']}", fg="blue")
        click.secho(f"  Existing:     {counters['skipped_existing']}", fg="blue")
    else:
        click.secho(
            f"  Would update: {counters['reported']}",
            fg="yellow",
        )
    click.secho(
        f"  Errors:       {counters['errors']}",
        fg="red" if counters["errors"] else "green",
    )
    click.secho(f"  Report rows:  {counters['reported']}", fg="blue")
    click.secho(f"\nAffected-datasets report written to: {report_path}", fg="green")

    if do_execute:
        click.secho(
            "\nNext step: rebuild the Solr index to surface the new field values:\n"
            "  ckan -c $CKAN_INI search-index rebuild",
            fg="yellow",
        )

    sys.stdout.flush()

    if counters["errors"]:
        raise SystemExit(1)
