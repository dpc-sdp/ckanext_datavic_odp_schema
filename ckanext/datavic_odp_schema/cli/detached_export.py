"""Export detached DD-DV dataset pairs with comparison to CSV.

DV datasets that have the same name as a DD dataset but are not linked by
syndicated_id are "detached". This command compares dataset and resource
metadata and writes one row per pair to CSV for review.
"""

from __future__ import annotations

import csv
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import click

import ckan.model as model
import ckan.plugins.toolkit as tk

from . import dd_api

log = __import__("logging").getLogger(__name__)

# Default directory for detached export CSV (when --csv-path not set). Adjust as needed.
DEFAULT_DETACHED_CSV_DIR = "/app/filestore/detached_syndicated_reports"

# Dataset fields to compare (from odp_dataset_schema.yaml dataset_fields),
# excluding category and personal_information. Adjust when schema changes.
DATASET_MATCH_FIELDS = [
    "title",
    "name",
    "alias",
    "notes",
    "extract",
    "tag_string",
    "owner_org",
    "license_id",
    "custom_licence_text",
    "custom_licence_link",
    "date_created_data_asset",
    "update_frequency",
    "full_metadata_url",
    "dtv_preview",
    "data_owner",
    "maintainer_email",
    "nominated_view_id",
    "nominated_view_resource",
]

RESOURCE_MATCH_FIELDS = [
    "name",
    "description",
    "release_date",
    "period_start",
    "period_end",
    "data_quality",
    "attribution",
]

# ---------------------------------------------------------------------------
# Field resolution
# ---------------------------------------------------------------------------


def _get_package_field_value(pkg: dict[str, Any], field: str) -> str:
    """Get dataset field value from package dict (top-level or extras)."""
    val = pkg.get(field)
    if val is not None and str(val).strip() != "":
        return str(val).strip()
    for extra in pkg.get("extras", []):
        if extra.get("key") == field:
            v = extra.get("value")
            if v is not None and str(v).strip() != "":
                return str(v).strip()
    return ""


def _normalize(val: Any) -> str:
    """Normalize for comparison: None/empty -> empty string."""
    if val is None:
        return ""
    s = str(val).strip()
    return s


def _is_external_resource_url(url: str | None) -> bool:
    """Return True if resource URL is external (not filestore/upload)."""
    if not url or not url.strip():
        return False
    url = url.strip()
    storage_path = tk.config.get("ckan.storage_path", "").strip()
    if storage_path and url.startswith(storage_path):
        return False
    site_url = (tk.config.get("ckan.site_url") or "").strip().rstrip("/")
    if site_url:
        if url.startswith(site_url + "/dataset/") or url.startswith(site_url + "/filestore/"):
            return False
    if "/filestore/" in url:
        return False
    return True


def _resource_fields_to_compare(resource: dict[str, Any]) -> list[str]:
    """List of resource fields to compare; includes url if external."""
    fields = list(RESOURCE_MATCH_FIELDS)
    if _is_external_resource_url(resource.get("url")):
        fields = fields + ["url"]
    return fields


def _get_resource_value(res: dict[str, Any], field: str) -> str:
    """Get resource field value."""
    return _normalize(res.get(field))


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _compare_datasets(
    dd_pkg: dict[str, Any],
    dv_pkg: dict[str, Any],
    dataset_fields: list[str],
) -> tuple[bool, list[str]]:
    """Compare dataset-level fields. Return (all_match, list of differing field names)."""
    differing = []
    for field in dataset_fields:
        dd_val = _normalize(_get_package_field_value(dd_pkg, field))
        dv_val = _normalize(_get_package_field_value(dv_pkg, field))
        if dd_val != dv_val:
            differing.append(field)
    return (len(differing) == 0, differing)


def _compare_resources(
    dd_resources: list[dict[str, Any]],
    dv_resources: list[dict[str, Any]],
) -> tuple[bool, list[str], list[str]]:
    """Compare resources by index. Return (all_match, resource_mismatch_lines, missing_lines)."""
    dd_n = len(dd_resources)
    dv_n = len(dv_resources)
    mismatch_parts: list[str] = []
    missing_parts: list[str] = []

    if dd_n > dv_n:
        for i in range(dv_n, dd_n):
            missing_parts.append(f"resource {i + 1} missing from DV")
    elif dv_n > dd_n:
        for i in range(dd_n, dv_n):
            missing_parts.append(f"resource {i + 1} missing from DD")

    n = min(dd_n, dv_n)
    all_match = True
    for i in range(n):
        dd_res = dd_resources[i]
        dv_res = dv_resources[i]
        fields = _resource_fields_to_compare(dd_res)
        # If DV resource is external, also compare url for that resource
        if _is_external_resource_url(dv_res.get("url")) and "url" not in fields:
            fields = fields + ["url"]
        diff_fields = []
        for f in fields:
            if _get_resource_value(dd_res, f) != _get_resource_value(dv_res, f):
                diff_fields.append(f)
                all_match = False
        if diff_fields:
            mismatch_parts.append(f"Resource {i + 1}: {', '.join(diff_fields)}")

    if missing_parts:
        all_match = False
    return (all_match, mismatch_parts, missing_parts)


def _build_comment(
    dataset_diff: list[str],
    resource_mismatches: list[str],
    resource_missing: list[str],
) -> str:
    """Build single comment string for CSV."""
    parts = []
    if dataset_diff:
        parts.append("Dataset: " + ", ".join(dataset_diff))
    if resource_mismatches:
        parts.append("; ".join(resource_mismatches))
    if resource_missing:
        parts.append("; ".join(resource_missing))
    return "; ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_CSV_COLUMNS = [
    "dd_package_id",
    "dd_name",
    "dv_package_id",
    "dv_name",
    "dataset_match",
    "dd_resource_total",
    "dv_resource_total",
    "all_resources_match",
    "comment",
]


def _fetch_dd_package(
    dd_url: str, dd_api_key: str, dd_name: str
) -> tuple[str, dict[str, Any] | None]:
    """Fetch one DD package by name. For use in thread pool. Returns (dd_name, pkg or None)."""
    try:
        pkg = dd_api.dd_package_show(dd_url, dd_api_key, dd_name)
        return (dd_name, pkg)
    except Exception as e:
        log.warning("DD package_show %s: %s", dd_name, e)
        return (dd_name, None)


@click.command("export-detached-syndicated-datasets")
@click.option(
    "--csv-path",
    default=None,
    type=click.Path(),
    help="Path for the CSV report. Default: <detached_csv_dir>/dv_detached_syndicated_<timestamp>.csv",
)
@click.option(
    "--workers",
    default=10,
    type=click.IntRange(1, 50),
    help="Number of parallel workers for DD API calls (default 10).",
)
def export_detached_syndicated_datasets(csv_path: str | None, workers: int) -> None:
    """Export detached DD-DV dataset pairs with comparison to CSV.

    Detached = same name on DD and DV but DD's syndicated_id is empty or
    points to a different DV package. For each pair, compares dataset and
    resource metadata and writes one row per pair.
    """
    click.secho("=== Export detached syndicated datasets ===\n", fg="cyan", bold=True)
    sys.stdout.flush()

    dd_url = dd_api._dd_url()
    dd_api_key = dd_api._dd_api_key()
    click.secho(f"DD URL: {dd_url}", fg="blue")
    sys.stdout.flush()

    # Fetch DD active packages
    click.secho("Fetching DD active dataset reference set...", fg="blue")
    sys.stdout.flush()
    dd_packages = dd_api.fetch_dd_active_packages(dd_url, dd_api_key)
    dd_by_name = {p["name"]: p for p in dd_packages}
    dd_names = set(dd_by_name)
    dd_syndicated_ids = {
        name: (dd_api._get_extra(pkg, "syndicated_id") or "")
        for name, pkg in dd_by_name.items()
    }
    click.secho(f"  DD reference: {len(dd_names)} active datasets.\n", fg="green")
    sys.stdout.flush()

    # DV datasets
    click.secho("Fetching DV local datasets...", fg="blue")
    sys.stdout.flush()
    dv_rows = (
        model.Session.query(
            model.Package.id,
            model.Package.name,
        )
        .filter(model.Package.type == "dataset")
        .all()
    )
    click.secho(f"  DV local: {len(dv_rows)} datasets.\n", fg="green")
    sys.stdout.flush()

    # Detached: same name on DD but syndicated_id != dv_id (or empty)
    detached = []
    for dv_id, dv_name in dv_rows:
        if dv_name not in dd_names:
            continue
        sid = dd_syndicated_ids.get(dv_name, "")
        if sid and sid == dv_id:
            continue
        dd_pkg_summary = dd_by_name[dv_name]
        detached.append((dd_pkg_summary["id"], dd_pkg_summary["name"], dv_id, dv_name))

    click.secho(f"Detached pairs (same name, not linked): {len(detached)}\n", fg="blue")
    sys.stdout.flush()

    # Fetch all DD packages in parallel (each unique dd_name once).
    # submit() queues work; worker threads run up to `workers` calls at a time.
    # We collect results as they complete (as_completed) and fill dd_pkg_by_name.
    unique_dd_names = list({dd_name for _, dd_name, _, _ in detached})
    click.secho(f"Fetching {len(unique_dd_names)} DD packages ({workers} workers)...", fg="blue")
    sys.stdout.flush()
    dd_pkg_by_name: dict[str, dict[str, Any] | None] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_name = {}
        for name in unique_dd_names:
            future = executor.submit(_fetch_dd_package, dd_url, dd_api_key, name)
            future_to_name[future] = name

        done = 0
        for future in as_completed(future_to_name):
            dd_name, pkg = future.result()
            dd_pkg_by_name[dd_name] = pkg
            done += 1
            if done % 50 == 0 or done == len(unique_dd_names):
                click.secho(f"  DD fetched {done}/{len(unique_dd_names)}...", fg="blue")
                sys.stdout.flush()

    click.secho("  DD fetch complete.\n", fg="green")
    sys.stdout.flush()

    dataset_fields = DATASET_MATCH_FIELDS
    context = {"model": model, "session": model.Session, "ignore_auth": True}
    context["user"] = tk.get_action("get_site_user")(context, {})["name"]

    rows = []
    for i, (dd_id, dd_name, dv_id, dv_name) in enumerate(detached):
        if (i + 1) % 100 == 0 or i == 0:
            click.secho(f"  Comparing pair {i + 1}/{len(detached)}: {dv_name}...", fg="blue")
            sys.stdout.flush()

        dd_pkg = dd_pkg_by_name.get(dd_name)
        if dd_pkg is None:
            rows.append({
                "dd_package_id": dd_id,
                "dd_name": dd_name,
                "dv_package_id": dv_id,
                "dv_name": dv_name,
                "dataset_match": "No",
                "dd_resource_total": "",
                "dv_resource_total": "",
                "all_resources_match": "No",
                "comment": "DD package_show returned empty or failed",
            })
            continue

        try:
            dv_pkg = tk.get_action("package_show")(context, {"id": dv_id})
        except Exception as e:
            log.warning("Error fetching DV package %s: %s", dv_id, e)
            rows.append({
                "dd_package_id": dd_id,
                "dd_name": dd_name,
                "dv_package_id": dv_id,
                "dv_name": dv_name,
                "dataset_match": "No",
                "dd_resource_total": str(len(dd_pkg.get("resources") or [])),
                "dv_resource_total": "",
                "all_resources_match": "No",
                "comment": f"Error: {e}",
            })
            continue

        dd_resources = dd_pkg.get("resources") or []
        dv_resources = dv_pkg.get("resources") or []

        dataset_ok, dataset_diff = _compare_datasets(
            dd_pkg, dv_pkg, dataset_fields
        )
        resources_ok, res_mismatches, res_missing = _compare_resources(
            dd_resources, dv_resources
        )

        comment = _build_comment(dataset_diff, res_mismatches, res_missing)

        rows.append({
            "dd_package_id": dd_id,
            "dd_name": dd_name,
            "dv_package_id": dv_id,
            "dv_name": dv_name,
            "dataset_match": "Yes" if dataset_ok else "No",
            "dd_resource_total": str(len(dd_resources)),
            "dv_resource_total": str(len(dv_resources)),
            "all_resources_match": "Yes" if resources_ok else "No",
            "comment": comment,
        })

    if not csv_path:
        ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(
            DEFAULT_DETACHED_CSV_DIR.rstrip("/"),
            f"dv_detached_syndicated_{ts}.csv",
        )
    csv_dir = os.path.dirname(csv_path)
    if csv_dir:
        os.makedirs(csv_dir, exist_ok=True)
    with open(csv_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    click.secho(f"\nCSV written to {csv_path}", fg="green")
    same_name_count = len([r for r in dv_rows if r[1] in dd_names])
    linked_count = len([r for r in dv_rows if r[1] in dd_names and dd_syndicated_ids.get(r[1]) == r[0]])
    click.secho(
        f"Summary: DV datasets={len(dv_rows)}, same name on DD={same_name_count} (linked={linked_count}, detached={len(detached)})",
        fg="cyan",
    )
    sys.stdout.flush()
