"""Sync selected fields from DD to DV for linked datasets.

Uses DD's syndicated_id to find DV packages that are syndicated from DD,
then patches DV records using CKAN actions (package_patch) in-process.
"""

from __future__ import annotations

import csv
import datetime
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import click

import ckan.model as model
import ckan.plugins.toolkit as tk

from . import dd_api

log = logging.getLogger(__name__)

# Fields to sync from DD to DV (package_patch keys). Add or remove as needed.
# Special handling: "category" is validated/resolved against DV groups (by id or name).
SYNC_FIELDS = [
    "category",
    "personal_information",
    "data_owner",
]

# Default directory for sync report CSV (when --report-path not set). Adjust as needed.
DEFAULT_SYNC_REPORT_DIR = "/app/filestore/sync_syndicated_reports"

# Default number of workers for parallel package_patch (only when not dry-run).
DEFAULT_SYNC_WORKERS = 8

_REPORT_COLUMNS = ["dv_id", "dv_name", "action"] + list(SYNC_FIELDS) + ["error_message"]


def _get_extra(pkg: dict[str, Any], key: str) -> str | None:
    """Get value from package top-level or extras."""
    return dd_api._get_extra(pkg, key)


def _dd_category_name(dd_pkg: dict[str, Any], category_id: str) -> str | None:
    """Get the group title or name from DD package's groups for the given category id."""
    for grp in dd_pkg.get("groups") or []:
        if grp.get("id") == category_id:
            return grp.get("title") or grp.get("name") or None
    return None


def _report_row(
    dv_id: str,
    dv_name: str,
    action: str,
    values: dict[str, str],
    error_message: str,
) -> dict[str, str]:
    """Build one report row with dv_id, dv_name, action, sync field columns, error_message."""
    row: dict[str, str] = {
        "dv_id": dv_id,
        "dv_name": dv_name,
        "action": action,
        "error_message": error_message,
    }
    for f in SYNC_FIELDS:
        row[f] = values.get(f, "")
    return row


def _patch_one(
    data: dict[str, Any],
    dv_id: str,
    dv_name: str,
    values: dict[str, str],
    site_user: str,
) -> tuple[str, str, str, dict[str, str], str]:
    """Run package_patch in the current thread (use with ThreadPoolExecutor).

    Uses a fresh session for this thread. Returns (action, dv_id, dv_name, values, error_message).
    """
    model.Session.remove()
    try:
        context = {
            "model": model,
            "session": model.Session,
            "ignore_auth": True,
            "user": site_user,
        }
        tk.get_action("package_patch")(context, data)
        model.Session.commit()
        return ("updated", dv_id, dv_name, values, "")
    except Exception as e:
        model.Session.rollback()
        return ("failed", dv_id, dv_name, values, str(e))


@click.command("sync-syndicated-fields")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Only report what would be updated; do not call package_patch.",
)
@click.option(
    "--report-path",
    default=None,
    type=click.Path(),
    help="Path for the CSV report. Default: <DEFAULT_SYNC_REPORT_DIR>/sync_syndicated_fields_<timestamp>.csv. Set to '' to skip writing a report.",
)
@click.option(
    "--workers",
    default=DEFAULT_SYNC_WORKERS,
    type=int,
    help=f"Number of parallel workers for package_patch (default {DEFAULT_SYNC_WORKERS}). Ignored when --dry-run.",
)
def sync_syndicated_fields(dry_run: bool, report_path: str | None, workers: int) -> None:
    """Sync configured fields (e.g. category, personal_information, data_owner) from DD to DV for linked datasets.

    Patches DV records using CKAN package_patch (in-process, no API key).
    Only updates DV datasets that are linked via DD's syndicated_id.
    Use export-detached-syndicated-datasets first to review detached pairs.
    """
    mode = "DRY-RUN" if dry_run else "SYNC"
    click.secho(f"=== Sync syndicated fields from DD [{mode}] ===\n", fg="cyan", bold=True)
    sys.stdout.flush()

    dd_url = dd_api._dd_url()
    dd_api_key = dd_api._dd_api_key()
    click.secho(f"DD URL: {dd_url}", fg="blue")
    sys.stdout.flush()

    click.secho("Fetching DD active dataset reference set...", fg="blue")
    sys.stdout.flush()
    dd_packages = dd_api.fetch_dd_active_packages(dd_url, dd_api_key)
    dd_by_syndicated_id: dict[str, dict] = {}
    for pkg in dd_packages:
        sid = _get_extra(pkg, "syndicated_id")
        if sid and sid.strip():
            dd_by_syndicated_id[sid.strip()] = pkg
    click.secho(
        f"  DD reference: {len(dd_packages)} active; {len(dd_by_syndicated_id)} with syndicated_id.\n",
        fg="green",
    )
    sys.stdout.flush()

    click.secho("Fetching DV local datasets...", fg="blue")
    sys.stdout.flush()
    dv_rows = (
        model.Session.query(model.Package.id, model.Package.name)
        .filter(model.Package.type == "dataset")
        .all()
    )
    click.secho(f"  DV local: {len(dv_rows)} datasets.\n", fg="green")
    sys.stdout.flush()

    to_update = [r for r in dv_rows if r[0] in dd_by_syndicated_id]
    click.secho(f"Linked (DD syndicated_id = DV id): {len(to_update)} datasets.\n", fg="blue")
    sys.stdout.flush()

    # Valid category IDs on DV (group type 'group'); map name/title -> id for fallback lookup
    dv_groups = list(model.Group.all("group"))
    dv_category_ids = {g.id for g in dv_groups}
    dv_group_id_by_name: dict[str, str] = {}
    for g in dv_groups:
        if g.title:
            dv_group_id_by_name[g.title.strip()] = g.id
        if g.name:
            dv_group_id_by_name[g.name.strip()] = g.id
    click.secho(f"DV categories (groups): {len(dv_category_ids)} available.\n", fg="blue")
    sys.stdout.flush()

    if not to_update:
        click.secho("Nothing to update.\n", fg="green")
        sys.stdout.flush()
        return

    skipped = 0
    report_rows: list[dict[str, str]] = []
    to_patch: list[tuple[dict[str, Any], str, str, dict[str, str]]] = []

    for dv_id, dv_name in to_update:
        dd_pkg = dd_by_syndicated_id[dv_id]
        values: dict[str, str] = {}
        for f in SYNC_FIELDS:
            v = _get_extra(dd_pkg, f) or dd_pkg.get(f)
            if v is None:
                values[f] = ""
            elif isinstance(v, str):
                values[f] = v.strip()
            else:
                values[f] = str(v)

        if not any(values[f] for f in SYNC_FIELDS):
            click.secho(f"  Skip {dv_name}: no sync fields on DD", fg="yellow")
            skipped += 1
            report_rows.append(_report_row(dv_id, dv_name, "skipped", values, "no sync fields on DD"))
            sys.stdout.flush()
            continue

        # Category from DD must exist on DV (by id or by group name); otherwise skip
        category = values.get("category")
        if category and "category" in SYNC_FIELDS and category not in dv_category_ids:
            dd_cat_name = _dd_category_name(dd_pkg, category)
            lookup_key = str(dd_cat_name).strip() if dd_cat_name else None
            resolved_id = dv_group_id_by_name.get(lookup_key) if lookup_key else None
            if resolved_id:
                values["category"] = resolved_id
            else:
                err = "category UUID not found on DV"
                if dd_cat_name:
                    err += f"; no DV group with matching name (DD category: {dd_cat_name!r})"
                else:
                    err += "; DD package has no group name for this category"
                click.secho(f"  Skip {dv_name}: {err}", fg="yellow")
                skipped += 1
                report_rows.append(_report_row(dv_id, dv_name, "skipped", values, err))
                sys.stdout.flush()
                continue

        data: dict[str, Any] = {"id": dv_id}
        for f in SYNC_FIELDS:
            if values.get(f):
                data[f] = values[f]

        if dry_run:
            click.secho(
                f"  Would patch {dv_name}: {', '.join(f'{f}={values.get(f)!r}' for f in SYNC_FIELDS if values.get(f))}",
                fg="cyan",
            )
            report_rows.append(_report_row(dv_id, dv_name, "would_update", values, ""))
            sys.stdout.flush()
            continue

        to_patch.append((data, dv_id, dv_name, values))


    site_user = tk.get_action("get_site_user")(
        {"model": model, "session": model.Session, "ignore_auth": True}, {}
    )["name"]

    # Run package_patch in parallel when not dry-run
    updated = 0
    failed = 0
    failed_names: list[str] = []
    if to_patch and not dry_run:
        n_workers = min(workers, len(to_patch))
        click.secho(f"  Patching {len(to_patch)} datasets ({n_workers} workers)...", fg="blue")
        sys.stdout.flush()
        done = 0
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {
                executor.submit(_patch_one, data, dv_id, dv_name, values, site_user): (dv_id, dv_name)
                for (data, dv_id, dv_name, values) in to_patch
            }
            for future in as_completed(futures):
                action, dv_id, dv_name, values, err_msg = future.result()
                report_rows.append(_report_row(dv_id, dv_name, action, values, err_msg))
                if action == "updated":
                    updated += 1
                else:
                    failed += 1
                    failed_names.append(dv_name)
                    log.error("Failed to patch %s (%s): %s", dv_name, dv_id, err_msg)
                    click.secho(f"  ERROR {dv_name}: {err_msg}", fg="red")
                done += 1
                if done % 50 == 0:
                    click.secho(f"  Patched {done}/{len(to_patch)}...", fg="green")
                    sys.stdout.flush()
    if dry_run:
        updated = sum(1 for r in report_rows if r.get("action") == "would_update")

    # ---- Summary ----------------------------------------------------------
    click.secho("\n--- Summary ---", fg="cyan", bold=True)
    click.secho(f"  Linked (DD syndicated_id = DV id): {len(to_update)}", fg="blue")
    click.secho(f"  Updated: {updated}", fg="green")
    click.secho(f"  Skipped (no sync fields on DD): {skipped}", fg="yellow")
    click.secho(f"  Failed: {failed}", fg="red" if failed else "green")
    if failed_names:
        click.secho("  Failed datasets:", fg="red")
        for name in failed_names[:20]:
            click.secho(f"    - {name}", fg="red")
        if len(failed_names) > 20:
            click.secho(f"    ... and {len(failed_names) - 20} more", fg="red")

    # ---- CSV report -------------------------------------------------------
    if report_path is not None:
        if not report_path.strip():
            pass
        else:
            csv_dir = os.path.dirname(report_path)
            if csv_dir:
                os.makedirs(csv_dir, exist_ok=True)
            with open(report_path, "w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=_REPORT_COLUMNS)
                writer.writeheader()
                writer.writerows(report_rows)
            click.secho(f"\nReport written to: {report_path}", fg="green")
    else:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(
            DEFAULT_SYNC_REPORT_DIR.rstrip("/"),
            f"sync_syndicated_fields_{ts}.csv",
        )
        csv_dir = os.path.dirname(report_path)
        if csv_dir:
            os.makedirs(csv_dir, exist_ok=True)
        with open(report_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=_REPORT_COLUMNS)
            writer.writeheader()
            writer.writerows(report_rows)
        click.secho(f"\nReport written to: {report_path}", fg="green")

    sys.stdout.flush()
