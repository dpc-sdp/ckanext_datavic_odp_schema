"""Sync selected fields from DD to DV for datasets linked via DD's syndicated_id.

Writes directly to ``package_extra`` / ``package`` table — no activity history,
no ``metadata_modified`` bump, no plugin hooks fired.

Run ``ckan -c $CKAN_INI search-index rebuild`` after the migration to update Solr.

Fields synced
-------------
Extras (package_extra):
  category, personal_information, data_owner, custom_licence_link

Core package column:
  maintainer_email
"""

from __future__ import annotations

import csv
import datetime
import logging
import os
import sys
import uuid
from typing import Any

import click

import ckan.model as model

from . import dd_api

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field lists
# ---------------------------------------------------------------------------

# Fields stored as package_extra rows on both DD and DV.
EXTRA_SYNC_FIELDS: list[str] = [
    "category",
    "personal_information",
    "data_owner",
    "custom_licence_link",
]

# Core CKAN package table columns to sync (not extras).
CORE_SYNC_FIELDS: list[str] = [
    "maintainer_email",
]

SYNC_FIELDS: list[str] = EXTRA_SYNC_FIELDS + CORE_SYNC_FIELDS

DEFAULT_SYNC_REPORT_DIR = "/app/filestore/sync_syndicated_reports"

_REPORT_COLUMNS = ["dv_id", "dv_name", "action"] + SYNC_FIELDS + ["warnings"]


def _get_field(pkg: dict[str, Any], key: str) -> str:
    """Return a non-empty field value from a package dict, or empty string."""
    return dd_api._get_extra(pkg, key) or ""


def _resolve_category(
    category_id: str,
    dv_category_ids: set[str],
) -> tuple[str, str]:
    """Resolve a DD category UUID to a DV group UUID.

    Returns ``(resolved_id, warning)``.  ``warning`` is empty on success.

    DD and DV share group UUIDs, so a direct match is expected for all datasets.
    """
    if category_id in dv_category_ids:
        return category_id, ""
    return "", f"category UUID {category_id!r} not found on DV"


# ---------------------------------------------------------------------------
# Direct DB write helpers
# ---------------------------------------------------------------------------


def _upsert_extra(
    session: Any, package_id: str, key: str, value: str
) -> str:
    """Upsert a ``package_extra`` row. Returns ``'inserted'``, ``'updated'``, or ``'unchanged'``."""
    existing = (
        session.query(model.PackageExtra)
        .filter_by(package_id=package_id, key=key)
        .first()
    )
    if existing:
        if existing.value == value and existing.state == "active":
            return "unchanged"
        existing.value = value
        existing.state = "active"
        return "updated"
    session.add(
        model.PackageExtra(
            id=str(uuid.uuid4()),
            package_id=package_id,
            key=key,
            value=value,
            state="active",
        )
    )
    return "inserted"


def _update_core_field(
    session: Any, package_id: str, field: str, value: str
) -> str:
    """Update a core ``package`` column. Returns ``'updated'`` or ``'unchanged'``."""
    pkg = session.query(model.Package).filter_by(id=package_id).first()
    if pkg is None:
        return "unchanged"
    current = getattr(pkg, field, None) or ""
    if current == value:
        return "unchanged"
    setattr(pkg, field, value)
    return "updated"


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------


def _report_row(
    dv_id: str,
    dv_name: str,
    action: str,
    values: dict[str, str],
    warnings: list[str],
) -> dict[str, str]:
    row: dict[str, str] = {
        "dv_id": dv_id,
        "dv_name": dv_name,
        "action": action,
        "warnings": "; ".join(warnings),
    }
    for f in SYNC_FIELDS:
        row[f] = values.get(f, "")
    return row


def _write_report(rows: list[dict[str, str]], path: str) -> None:
    csv_dir = os.path.dirname(path)
    if csv_dir:
        os.makedirs(csv_dir, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    click.secho(f"\nReport written to: {path}", fg="green")


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command("sync-syndicated-fields")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report what would be written without making any DB changes.",
)
@click.option(
    "--report-path",
    default=None,
    type=click.Path(),
    help=(
        "Path for the CSV report. "
        "Defaults to <DEFAULT_SYNC_REPORT_DIR>/sync_syndicated_fields_<timestamp>.csv."
    ),
)
def sync_syndicated_fields(dry_run: bool, report_path: str | None) -> None:
    """Sync fields from DD to DV for datasets linked via DD's syndicated_id.

    Writes directly to ``package_extra`` / ``package`` table — no activity
    history, no ``metadata_modified`` update, no plugin hooks.

    After running, rebuild the Solr index:

        ckan -c $CKAN_INI search-index rebuild

    Fields synced: category, personal_information, data_owner,
    custom_licence_link, maintainer_email.
    """
    mode = "DRY-RUN" if dry_run else "SYNC"
    click.secho(f"=== Sync syndicated fields from DD [{mode}] ===\n", fg="cyan", bold=True)
    sys.stdout.flush()

    dd_url = dd_api._dd_url()
    dd_key = dd_api._dd_api_key()
    click.secho(f"DD URL: {dd_url}\n", fg="blue")
    sys.stdout.flush()

    # ---- Fetch DD active packages ----------------------------------------
    click.secho("Fetching DD active datasets...", fg="blue")
    sys.stdout.flush()
    dd_packages = dd_api.fetch_dd_active_packages(dd_url, dd_key)

    # Keyed by DV package UUID (DD's syndicated_id extra).
    dd_by_dv_id: dict[str, dict[str, Any]] = {}
    for pkg in dd_packages:
        sid = _get_field(pkg, "syndicated_id")
        if sid:
            dd_by_dv_id[sid] = pkg

    click.secho(
        f"  {len(dd_packages)} active DD datasets; "
        f"{len(dd_by_dv_id)} with syndicated_id.\n",
        fg="green",
    )
    sys.stdout.flush()

    # ---- Load DV category groups for resolution --------------------------
    dv_groups = list(model.Group.all("group"))
    dv_category_ids = {g.id for g in dv_groups}
    click.secho(f"DV categories (groups): {len(dv_category_ids)} available.\n", fg="blue")
    sys.stdout.flush()

    # ---- Load all DV datasets --------------------------------------------
    # No state filter — the DD-side query already restricts to active+published
    # packages, so dd_by_dv_id only contains UUIDs for active DD datasets.
    # Including non-active DV datasets ensures fields are populated even for
    # deleted/draft datasets that may be restored later.
    click.secho("Loading DV datasets...", fg="blue")
    sys.stdout.flush()
    dv_rows = (
        model.Session.query(model.Package.id, model.Package.name)
        .filter(model.Package.type == "dataset")
        .all()
    )
    to_sync = [(dv_id, dv_name) for dv_id, dv_name in dv_rows if dv_id in dd_by_dv_id]
    click.secho(
        f"  {len(dv_rows)} DV datasets; {len(to_sync)} linked to DD.\n",
        fg="green",
    )
    sys.stdout.flush()

    if not to_sync:
        click.secho("Nothing to sync.\n", fg="green")
        sys.stdout.flush()
        return

    # ---- Sync loop -------------------------------------------------------
    report_rows: list[dict[str, str]] = []
    counters = {"updated": 0, "skipped": 0, "error": 0}

    for i, (dv_id, dv_name) in enumerate(to_sync):
        dd_pkg = dd_by_dv_id[dv_id]
        values: dict[str, str] = {}
        warnings: list[str] = []

        # Resolve each field value from the DD package dict.
        for f in EXTRA_SYNC_FIELDS:
            if f == "category":
                raw = _get_field(dd_pkg, "category")
                if raw:
                    resolved, warn = _resolve_category(raw, dv_category_ids)
                    values["category"] = resolved
                    if warn:
                        warnings.append(warn)
                else:
                    values["category"] = ""
            else:
                values[f] = _get_field(dd_pkg, f)

        for f in CORE_SYNC_FIELDS:
            values[f] = _get_field(dd_pkg, f)

        fields_to_write = {f: v for f, v in values.items() if v}

        if not fields_to_write:
            counters["skipped"] += 1
            report_rows.append(_report_row(dv_id, dv_name, "skipped_no_values", values, warnings))
            continue

        if (i + 1) % 500 == 0:
            click.secho(f"  Processing {i + 1}/{len(to_sync)}...", fg="blue")
            sys.stdout.flush()

        if dry_run:
            parts = ", ".join(f"{f}={v!r}" for f, v in fields_to_write.items())
            click.secho(f"  Would write {dv_name}: {parts}", fg="cyan")
            report_rows.append(_report_row(dv_id, dv_name, "would_update", values, warnings))
            counters["updated"] += 1
            sys.stdout.flush()
            continue

        try:
            for f, v in fields_to_write.items():
                if f in EXTRA_SYNC_FIELDS:
                    _upsert_extra(model.Session, dv_id, f, v)
                else:
                    _update_core_field(model.Session, dv_id, f, v)
            model.Session.commit()
            action = "updated"
            counters["updated"] += 1
        except Exception as exc:
            model.Session.rollback()
            action = "error"
            counters["error"] += 1
            warnings.append(str(exc))
            log.error("Failed to write %s (%s): %s", dv_name, dv_id, exc)
            click.secho(f"  ERROR {dv_name}: {exc}", fg="red")

        report_rows.append(_report_row(dv_id, dv_name, action, values, warnings))

    # ---- Summary ---------------------------------------------------------
    click.secho("\n--- Summary ---", fg="cyan", bold=True)
    click.secho(f"  Linked:   {len(to_sync)}", fg="blue")
    click.secho(f"  Updated:  {counters['updated']}", fg="green")
    click.secho(f"  Skipped:  {counters['skipped']}", fg="yellow")
    click.secho(
        f"  Errors:   {counters['error']}",
        fg="red" if counters["error"] else "green",
    )
    if not dry_run:
        click.secho(
            "\nNext step — rebuild the Solr index to surface the new field values:\n"
            "  ckan -c $CKAN_INI search-index rebuild",
            fg="yellow",
        )
    sys.stdout.flush()

    # ---- CSV report ------------------------------------------------------
    if not report_path:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(
            DEFAULT_SYNC_REPORT_DIR.rstrip("/"),
            f"sync_syndicated_fields_{ts}.csv",
        )
    _write_report(report_rows, report_path)
    sys.stdout.flush()
