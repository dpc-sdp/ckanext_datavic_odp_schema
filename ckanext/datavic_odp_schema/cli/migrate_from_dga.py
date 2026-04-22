"""Migrate Victorian local council orgs, datasets, and resources from data.gov.au to DataVic.

Acceptance criteria covered: AC1 (orgs), AC2 (datasets), AC3 (resources), AC5 (re-run safety).
AC4 (external harvest round-trip) requires no script changes — it depends only on preserved IDs.

Usage
-----
    ckan -c $CKAN_INI datavic-odp migrate-from-data-gov-au [--org SLUG] [--max-filesize-mb N]

Reads the bundled council list from ``/app/ckan/default/vic-councils.csv`` by default.
Pass ``--csv-path`` to override (useful for local testing).
"""

from __future__ import annotations

import csv
import datetime
import json
import logging
import os
import re
import sys
import tempfile
from typing import Any
from urllib.parse import urlparse
from werkzeug.datastructures import FileStorage

import click
import ckanapi

import ckan.model as model
import ckan.plugins.toolkit as tk
from ckan.model import Package

from . import dga_client as dga

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CSV_PATH = "/app/ckan/default/vic-councils.csv"
DEFAULT_REPORT_DIR = "/app/filestore/datagov_migration"
DEFAULT_BACKUP_DIR = "/app/filestore/datagov_migration/backups"

DGA_BASE_URL = dga.DGA_BASE_URL

# Fixed dataset defaults (AC2)
FIXED_CATEGORY = "9ca71dfb-b758-4901-97ba-08cebe923158"
FIXED_PERSONAL_INFO = "no"

# Fallback tag when the DGA dataset has no tags
TAG_FALLBACK = "local government"

# License mapping: DGA license_id → DV license_id
LICENSE_MAP: dict[str, str] = {
    "cc-by": "cc-by",
    "cc-by-2.5": "cc-by",
    "cc-by-4.0": "cc-by",
    "cc-by-sa": "cc-by-sa",
    "cc-nc": "cc-nc",
    "other-nc": "cc-nc",
    "other": "other",
    "other-open": "other",
    "other-forsale": "other",
    "other-unpublished": "other",
    "pdm": "other",
    "oecd-data": "other",
}
LICENSE_FALLBACK = "cc-by"

# Update-frequency mapping: DGA extras[update_freq] → DV update_frequency
# Schema enum casing is authoritative (asNeeded, notPlanned, not lowercase).
FREQUENCY_MAP: dict[str, str] = {
    "daily": "daily",
    "weekly": "weekly",
    "monthly": "monthly",
    "quarterly": "quarterly",
    "biannually": "biannually",
    "biennaully": "biannually",  # DGA typo for "biennially"
    "annually": "annually",
    "infrequently": "irregular",
    "other": "unknown",
    "never": "notPlanned",
}
FREQUENCY_FALLBACK = "unknown"

# Audit CSV columns
_REPORT_COLUMNS = [
    "org_slug",
    "stage",
    "dga_id",
    "dv_id",
    "name",
    "status",
    "reason",
    "flags",
]

PACKAGE_NAME_MAX_LENGTH = getattr(Package, "name_max_length", 100)

# ---------------------------------------------------------------------------
# Helpers — field mapping
# ---------------------------------------------------------------------------


def _get_extra(pkg: dict, key: str) -> str:
    """Return extra value from a CKAN package dict, or empty string."""
    for extra in pkg.get("extras", []):
        if extra.get("key") == key:
            return extra.get("value") or ""
    return ""


def _map_license(dga_license_id: str) -> tuple[str, str]:
    """Map a DGA license_id to a DV license_id.

    Returns ``(dv_license_id, flag)`` where flag is one of:
    ``''`` (clean match), ``'license_unmapped'`` (no DV equivalent, using other),
    ``'license_fallback'`` (empty/unknown, defaulting to cc-by).
    """
    if not dga_license_id:
        return LICENSE_FALLBACK, "license_fallback"
    mapped = LICENSE_MAP.get(dga_license_id)
    if mapped:
        # Flag licenses with no true DV equivalent
        if dga_license_id in ("pdm", "oecd-data", "other-forsale", "other-unpublished"):
            return mapped, "license_unmapped"
        return mapped, ""
    return LICENSE_FALLBACK, "license_fallback"


def _map_frequency(pkg: dict) -> tuple[str, str]:
    """Map DGA extras[update_freq] to DV update_frequency.

    Returns ``(dv_value, flag)`` where flag is ``'freq_fallback'`` when the
    field is absent/empty, else ``''``.
    """
    raw = _get_extra(pkg, "update_freq").strip().lower()
    if not raw:
        return FREQUENCY_FALLBACK, "freq_fallback"
    mapped = FREQUENCY_MAP.get(raw)
    if mapped:
        return mapped, ""
    return FREQUENCY_FALLBACK, "freq_fallback"


def _build_tags(pkg: dict) -> tuple[list[dict[str, str]], str]:
    """Build DV tags from DGA tags.

    Returns ``(tags, flag)`` where flag is ``'tag_fallback'`` when
    the fallback tag is used.
    """
    names = [(t.get("name") or "").strip() for t in pkg.get("tags", [])]
    names = [name for name in names if name]

    if names:
        return [{"name": name} for name in names], ""

    return [{"name": TAG_FALLBACK}], "tag_fallback"


def _resource_name(resource: dict) -> str:
    """Return resource name, falling back to the URL basename."""
    name = (resource.get("name") or "").strip()
    if name:
        return name
    url = resource.get("url", "")
    return os.path.basename(urlparse(url).path) or "resource"


# ---------------------------------------------------------------------------
# Helpers — CSV loading
# ---------------------------------------------------------------------------

def normalize_cell(value: str | None) -> str:
    """Normalize a CSV cell value by removing common encoding artifacts.

    Removes the following characters wherever they appear:
    - \\u00a0: non-breaking space (NBSP)
    - \\ufffd: Unicode replacement character (�)
    - \\ufeff: byte order mark (BOM)

    Also trims leading/trailing whitespace. Returns an empty string for None.
    """
    if not value:
        return ""
    for ch in "\u00a0\ufffd\ufeff":
        value = value.replace(ch, "")
    return value.strip()


def _load_councils(csv_path: str) -> list[dict[str, str]]:
    """Load council records from a CSV file and normalize all fields.

    Applies ``normalize_cell`` to both column names and values to remove
    encoding artifacts and trim whitespace.

    Returns:
        A list of dictionaries with cleaned keys and values
        (e.g. Organisation, URL, Org Slug).
    """
    councils = []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            clean = {normalize_cell(k): normalize_cell(v) for k, v in row.items()}
            councils.append(clean)
    return councils


# ---------------------------------------------------------------------------
# Helpers — audit CSV
# ---------------------------------------------------------------------------


def _make_report_path(report_dir: str) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(report_dir, exist_ok=True)
    return os.path.join(report_dir, f"datagov_migration_{ts}.csv")


def _open_report(path: str):
    """Open the audit CSV for writing; return (file_handle, DictWriter)."""
    fh = open(path, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(fh, fieldnames=_REPORT_COLUMNS)
    writer.writeheader()
    return fh, writer


def _audit_row(
    org_slug: str,
    stage: str,
    dga_id: str,
    dv_id: str,
    name: str,
    status: str,
    reason: str = "",
    flags: list[str] | None = None,
) -> dict:
    return {
        "org_slug": org_slug,
        "stage": stage,
        "dga_id": dga_id,
        "dv_id": dv_id,
        "name": name,
        "status": status,
        "reason": reason,
        "flags": "; ".join(flags or []),
    }


# ---------------------------------------------------------------------------
# Helpers — DGA payload JSON capture
# ---------------------------------------------------------------------------


def _save_payload_json(data: list | dict, backup_dir: str, filename: str) -> str:
    """Save data as JSON and return the file path.

    Uses default=str for json.dump to handle datetime and other non-serializable objects.
    """
    os.makedirs(backup_dir, exist_ok=True)
    filepath = os.path.join(backup_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return filepath


def _make_backup_run_dir(backup_dir: str) -> str:
    """Create a timestamped backup directory for this migration run."""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(backup_dir, ts)
    os.makedirs(path, exist_ok=True)
    return path


def _safe_filename_part(value: str) -> str:
    """Return a filesystem-safe token for JSON capture filenames."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "unknown"


# ---------------------------------------------------------------------------
# CKAN action context
# ---------------------------------------------------------------------------


def _site_context() -> dict:
    """Return a CKAN action context using the site user (bypasses auth).

    CKAN's create actions (organization_create, package_create) require a
    valid ``user`` in the context even when ``ignore_auth`` is True — they
    use it to record the creator.  ``get_site_user`` creates the site user
    on first call if it doesn't exist yet.
    """
    site_user = tk.get_action("get_site_user")({"ignore_auth": True}, {})
    return {"ignore_auth": True, "user": site_user["name"]}


def _dv_org_exists(org_id: str) -> bool:
    try:
        tk.get_action("organization_show")(_site_context(), {"id": org_id})
        return True
    except tk.ObjectNotFound:
        return False


def _dv_dataset_exists(dataset_id: str) -> bool:
    try:
        tk.get_action("package_show")(_site_context(), {"id": dataset_id})
        return True
    except tk.ObjectNotFound:
        return False


# ---------------------------------------------------------------------------
# Migration steps
# ---------------------------------------------------------------------------


def _migrate_org(
    client: ckanapi.RemoteCKAN,
    slug: str,
    backup_run_dir: str,
    writer: csv.DictWriter,
    counters: dict,
) -> tuple[str, str] | None:
    """Migrate a single org (AC1). Returns the DV (org_id, org_email), or None on failure."""
    try:
        dga_org = dga.org_show(client, slug)
    except Exception as exc:
        log.error("Failed to fetch org %r from DGA: %s", slug, exc)
        writer.writerow(_audit_row(slug, "org", "", "", slug, "failed", str(exc)))
        counters["org_failed"] += 1
        return None

    try:
        safe_slug = _safe_filename_part(slug)
        filepath = _save_payload_json(dga_org, backup_run_dir, f"org_{safe_slug}.json")
        log.info("Saved DGA org_show payload to %s", filepath)
    except Exception as exc:
        log.warning("Failed to save org_show payload for %s: %s", slug, exc)

    dga_id = dga_org["id"]
    dga_org_email = (dga_org.get("email") or "").strip()

    if _dv_org_exists(dga_id):
        click.secho(f"  org {slug}: already exists on DV — skipping create", fg="yellow")
        writer.writerow(_audit_row(slug, "org", dga_id, dga_id, slug, "skipped"))
        counters["org_skipped"] += 1
        return dga_id, dga_org_email

    # Build org payload
    org_data: dict[str, Any] = {
        "id": dga_id,
        "name": dga_org["name"],
        "title": dga_org.get("title", ""),
        "description": dga_org.get("description", ""),
    }

    # Download and attach org image
    image_url = dga_org.get("image_display_url") or dga_org.get("image_url") or ""
    tmp_path: str | None = None
    image_upload_fh: Any = None

    if image_url:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=_image_suffix(image_url)) as tmp:
                tmp_path = tmp.name
            dga.download_file(image_url, tmp_path, max_bytes=10 * 1024 * 1024)
            image_upload_fh = open(tmp_path, "rb")
            org_data["image_upload"] = image_upload_fh
        except Exception as exc:
            log.warning("Image download failed for %r (%s); creating org without image", slug, exc)
            org_data.pop("image_upload", None)
            if image_upload_fh:
                try:
                    image_upload_fh.close()
                except Exception:
                    pass

    try:
        tk.get_action("organization_create")(_site_context(), org_data)
    finally:
        if image_upload_fh:
            try:
                image_upload_fh.close()
            except Exception:
                pass
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    click.secho(f"  org {slug}: created (id={dga_id})", fg="green")
    writer.writerow(_audit_row(slug, "org", dga_id, dga_id, slug, "created"))
    counters["org_created"] += 1

    return dga_id, dga_org_email


def _image_suffix(url: str) -> str:
    """Return a file extension (with dot) inferred from the URL, defaulting to .jpg."""
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext if ext else ".jpg"


def _is_valid_email(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return False

    validator = tk.get_validator("email_validator")

    try:
        validator(value, {})
        return True
    except tk.Invalid:
        return False


def _is_valid_contact_point(value: str) -> bool:
    """Return True when value is a valid email or HTTP(S) URL."""
    value = (value or "").strip()
    if not value:
        return False
    if _is_valid_email(value):
        return True

    try:
        parsed = urlparse(value)
    except (TypeError, ValueError):
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _build_dataset_payload(
    dga_pkg: dict,
    dv_org_id: str,
    dv_org_email: str,
    flags_out: list[str],
) -> dict[str, Any]:
    """Map a DGA package dict to a DV package_create payload.

    Populates ``flags_out`` in place with any audit flags encountered.
    """
    notes = dga_pkg.get("notes") or ""
    extract = notes[:200]

    tags, tag_flag = _build_tags(dga_pkg)
    if tag_flag:
        flags_out.append(tag_flag)

    dga_license = dga_pkg.get("license_id") or ""
    dv_license, lic_flag = _map_license(dga_license)
    if lic_flag:
        flags_out.append(lic_flag)

    dv_freq, freq_flag = _map_frequency(dga_pkg)
    if freq_flag:
        flags_out.append(freq_flag)

    date_created = dga_pkg.get("temporal_coverage_from") or ""
    dga_name = dga_pkg.get("name") or ""

    dga_contact_point = (dga_pkg.get("contact_point") or "").strip()
    if _is_valid_contact_point(dga_contact_point):
        contact_point = dga_contact_point
    else:
        contact_point = (dv_org_email or "").strip()
        if contact_point and not _is_valid_contact_point(contact_point):
            contact_point = ""
        if dga_contact_point:
            if contact_point:
                flags_out.append("contact_point_not_email_org_email_used")
            else:
                flags_out.append("contact_point_not_email_no_fallback")

    return {
        "id": dga_pkg["id"],
        "title": dga_pkg.get("title") or "",
        "name": dga_name,
        "notes": notes,
        "extract": extract,
        "tags": tags,
        "owner_org": dv_org_id,
        "license_id": dv_license,
        "data_owner": dga_pkg.get("author") or "",
        "contact_point": contact_point,
        "date_created_data_asset": date_created,
        "update_frequency": dv_freq,
        "full_metadata_url": f"{DGA_BASE_URL}/dataset/{dga_name}" if dga_name else "",
        "category": FIXED_CATEGORY,
        "personal_information": FIXED_PERSONAL_INFO,
        "private": False,
    }


def _package_name_exists(name: str) -> bool:
    validator = tk.get_validator("package_name_exists")
    try:
        validator(name, {"model": model, "session": model.Session})
        return True
    except tk.Invalid:
        return False


def _next_available_package_name(base_name: str, max_suffix: int = 999) -> str:
    base_name = re.sub(r"-+", "-", (base_name or "").strip()).strip("-")
    if not base_name:
        base_name = "dataset"

    base_name = base_name[:PACKAGE_NAME_MAX_LENGTH]

    if not _package_name_exists(base_name):
        return base_name

    for i in range(1, max_suffix + 1):
        suffix = str(i)
        candidate = base_name[: PACKAGE_NAME_MAX_LENGTH - len(suffix)] + suffix
        if not _package_name_exists(candidate):
            return candidate

    # This is extremely unlikely, but if we exhaust all suffixes, return the base name.
    return base_name


def _migrate_dataset(
    dga_pkg: dict,
    dv_org_id: str,
    dv_org_email: str,
    org_slug: str,
    writer: csv.DictWriter,
    counters: dict,
    max_filesize_bytes: int,
) -> None:
    """Migrate a single dataset and its resources (AC2, AC3, AC5)."""
    dga_id = dga_pkg["id"]
    dga_name = dga_pkg.get("name") or dga_id

    # AC5: skip if already on DV
    if _dv_dataset_exists(dga_id):
        writer.writerow(_audit_row(org_slug, "dataset", dga_id, dga_id, dga_name, "skipped"))
        counters["dataset_skipped"] += 1
        return

    flags: list[str] = []
    reason: str = ""
    try:
        payload = _build_dataset_payload(dga_pkg, dv_org_id, dv_org_email, flags)
        original_name = payload["name"]
        unique_name = _next_available_package_name(original_name)

        if unique_name != original_name:
            payload["name"] = unique_name
            flags.append("name_collision_renamed")
            reason = f"{original_name} -> {unique_name}"
        
        dv_pkg = tk.get_action("package_create")(_site_context(), payload)
        dv_pkg_id = dv_pkg["id"]
    except Exception as exc:
        log.error("package_create failed for %r (%s): %s", dga_name, dga_id, exc)
        writer.writerow(
            _audit_row(org_slug, "dataset", dga_id, "", dga_name, "failed", str(exc), flags)
        )
        counters["dataset_failed"] += 1
        return

    writer.writerow(
        _audit_row(org_slug, "dataset", dga_id, dv_pkg_id, dga_name, "created", reason, flags)
    )
    counters["dataset_created"] += 1

    # Temporal fields for resource period_start / period_end
    period_start = dga_pkg.get("temporal_coverage_from") or ""
    period_end = dga_pkg.get("temporal_coverage_to") or ""

    for resource in dga_pkg.get("resources", []):
        _migrate_resource(
            resource=resource,
            dv_pkg_id=dv_pkg_id,
            dga_pkg_id=dga_id,
            org_slug=org_slug,
            period_start=period_start,
            period_end=period_end,
            writer=writer,
            counters=counters,
            max_filesize_bytes=max_filesize_bytes,
        )


def _migrate_resource(
    resource: dict,
    dv_pkg_id: str,
    dga_pkg_id: str,
    org_slug: str,
    period_start: str,
    period_end: str,
    writer: csv.DictWriter,
    counters: dict,
    max_filesize_bytes: int,
) -> None:
    """Migrate a single resource (AC3)."""
    dga_res_id = resource.get("id") or ""
    res_name = _resource_name(resource)
    url = resource.get("url") or ""
    flags: list[str] = []

    base_payload: dict[str, Any] = {
        "package_id": dv_pkg_id,
        "name": res_name,
        "description": resource.get("description") or "",
        "format": resource.get("format") or "",
        "release_date": (resource.get("created") or "")[:10],
        "period_start": period_start,
        "period_end": period_end,
    }
    if resource.get("size"):
        base_payload["filesize"] = resource["size"]

    is_upload = resource.get("url_type") == "upload"

    if is_upload and url:
        # Check size before downloading
        remote_size = dga.head_size(url)
        if remote_size is not None and remote_size > max_filesize_bytes:
            # Over cap — store DGA URL as-is
            flags.append("over_cap")
            _create_linked_resource(base_payload, url, dv_pkg_id, org_slug, dga_pkg_id, dga_res_id,
                                    res_name, writer, counters, flags)
            return

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=_res_suffix(res_name)) as tmp:
                tmp_path = tmp.name

            dga.download_file(url, tmp_path, max_bytes=max_filesize_bytes)

            with open(tmp_path, "rb") as upload_fh:
                resource_payload = dict(base_payload)
    
                # CKAN expects file uploads as FileStorage objects in the payload.
                resource_payload["upload"] = FileStorage(
                    stream=upload_fh,
                    filename=res_name,
                    content_type="application/octet-stream",
                )
                dv_res = tk.get_action("resource_create")(_site_context(), resource_payload)
            writer.writerow(
                _audit_row(org_slug, "resource", dga_res_id, dv_res["id"], res_name,
                           "created", "", flags)
            )
            counters["resource_uploaded"] += 1
        except dga.FileTooLargeError:
            flags.append("over_cap")
            log.warning("Resource %r exceeded size cap mid-download; storing DGA URL", res_name)
            _create_linked_resource(base_payload, url, dv_pkg_id, org_slug, dga_pkg_id, dga_res_id,
                                    res_name, writer, counters, flags)
        except Exception as exc:
            log.error("resource upload failed for %r in pkg %s: %s", res_name, dga_pkg_id, exc)
            writer.writerow(
                _audit_row(org_slug, "resource", dga_res_id, "", res_name, "failed", str(exc), flags)
            )
            counters["resource_failed"] += 1
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
    else:
        # Linked resource — pass URL through
        flags.append("linked_resource")
        _create_linked_resource(base_payload, url, dv_pkg_id, org_slug, dga_pkg_id, dga_res_id,
                                res_name, writer, counters, flags)


def _create_linked_resource(
    base_payload: dict,
    url: str,
    dv_pkg_id: str,
    org_slug: str,
    dga_pkg_id: str,
    dga_res_id: str,
    res_name: str,
    writer: csv.DictWriter,
    counters: dict,
    flags: list[str],
) -> None:
    """Create a resource on DV using an external URL (no upload)."""
    try:
        resource_payload = dict(base_payload)
        resource_payload["url"] = url
        dv_res = tk.get_action("resource_create")(_site_context(), resource_payload)
        status = "kept-as-url" if "over_cap" in flags else "created"
        writer.writerow(
            _audit_row(org_slug, "resource", dga_res_id, dv_res["id"], res_name,
                       status, "", flags)
        )
        counters["resource_linked"] += 1
    except Exception as exc:
        log.error("resource_create (linked) failed for %r in pkg %s: %s", res_name, dga_pkg_id, exc)
        writer.writerow(
            _audit_row(org_slug, "resource", dga_res_id, "", res_name, "failed", str(exc), flags)
        )
        counters["resource_failed"] += 1


def _res_suffix(name: str) -> str:
    _, ext = os.path.splitext(name)
    return ext if ext else ""


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command("migrate-from-data-gov-au")
@click.option(
    "--org",
    "org_slugs",
    multiple=True,
    metavar="SLUG",
    help=(
        "Org slug(s) to migrate. Repeatable. "
        "If omitted, all 39 Victorian councils in the bundled CSV are migrated."
    ),
)
@click.option(
    "--max-filesize-mb",
    default=100,
    show_default=True,
    type=int,
    help="Files larger than this (MB) are stored as DGA URLs rather than re-uploaded.",
)
@click.option(
    "--csv-path",
    default=DEFAULT_CSV_PATH,
    show_default=True,
    type=click.Path(exists=True),
    help="Path to the council list CSV. Override for local testing.",
)
@click.option(
    "--report-dir",
    default=DEFAULT_REPORT_DIR,
    show_default=True,
    help="Directory for the per-run audit CSV report.",
)
@click.option(
    "--backup-dir",
    default=DEFAULT_BACKUP_DIR,
    show_default=True,
    help="Directory for JSON backups of org and package payloads from data.gov.au.",
)
@click.pass_context
def migrate_from_data_gov_au(
    ctx: click.Context,
    org_slugs: tuple[str, ...],
    max_filesize_mb: int,
    csv_path: str,
    report_dir: str,
    backup_dir: str,
) -> None:
    """Migrate Victorian local council orgs, datasets, and resources from data.gov.au to DataVic.

    Reads from data.gov.au (DGA) via CKAN API and writes to the local DV instance
    using CKAN actions.  Safe to re-run: existing DV datasets (matched by preserved
    DGA id) are skipped (AC5).
    """
    click.secho("=== DataVic ← data.gov.au Council Migration ===\n", fg="cyan", bold=True)
    sys.stdout.flush()

    max_filesize_bytes = max_filesize_mb * 1024 * 1024

    # Load council list
    try:
        councils = _load_councils(csv_path)
    except Exception as exc:
        click.secho(f"Failed to load council CSV from {csv_path!r}: {exc}", fg="red")
        sys.exit(1)

    # Filter to requested orgs if --org given
    if org_slugs:
        slug_set = {s.lower() for s in org_slugs}
        councils = [c for c in councils if c.get("Org Slug", "").lower() in slug_set]
        if not councils:
            click.secho(
                f"No matching councils found for slugs: {', '.join(org_slugs)}", fg="red"
            )
            sys.exit(1)

    click.secho(f"Orgs to migrate: {len(councils)}", fg="blue")
    click.secho(f"Max file size:   {max_filesize_mb} MB", fg="blue")
    click.secho(f"Council CSV:     {csv_path}", fg="blue")
    click.secho(f"Report dir:      {report_dir}", fg="blue")
    backup_run_dir = _make_backup_run_dir(backup_dir)
    click.secho(f"Backup dir:      {backup_run_dir}\n", fg="blue")
    sys.stdout.flush()

    report_path = _make_report_path(report_dir)
    report_fh, writer = _open_report(report_path)

    client = dga.get_dga_client()

    counters: dict[str, int] = {
        "org_created": 0,
        "org_skipped": 0,
        "org_failed": 0,
        "dataset_created": 0,
        "dataset_skipped": 0,
        "dataset_failed": 0,
        "resource_uploaded": 0,
        "resource_linked": 0,
        "resource_failed": 0,
    }

    try:
        app = ctx.meta["flask_app"]
        # Use test_request_context for CLI operations to provide Flask request context
        # that plugins like fortify expect when creating/modifying organizations
        with app.test_request_context():
            # Set up the user context for plugins that expect toolkit.g.userobj
            from ckan import model
            site_user = tk.get_action("get_site_user")({"ignore_auth": True}, {})
            tk.g.userobj = model.User.get(site_user["name"])
            
            for council in councils:
                slug = council.get("Org Slug") or council.get("org_slug") or ""
                if not slug:
                    click.secho(f"  Skipping row with missing slug: {council}", fg="yellow")
                    continue

                click.secho(f"\n--- {slug} ---", fg="cyan", bold=True)
                sys.stdout.flush()

                org_result = _migrate_org(client, slug, backup_run_dir, writer, counters)
                if org_result is None:
                    click.secho(f"  Skipping datasets for {slug} (org migration failed)", fg="red")
                    continue

                dv_org_id, dv_org_email = org_result

                dataset_count = 0
                org_packages = list(dga.iter_org_packages(client, slug))

                try:
                    safe_slug = _safe_filename_part(slug)
                    filepath = _save_payload_json(
                        org_packages, backup_run_dir, f"datasets_{safe_slug}.json"
                    )
                    log.info(
                        "Saved DGA iter_org_packages payload (%s packages) to %s",
                        len(org_packages),
                        filepath,
                    )
                except Exception as exc:
                    log.warning("Failed to save iter_org_packages payload for %s: %s", slug, exc)

                for dga_pkg in org_packages:
                    dataset_count += 1

                    if dataset_count % 50 == 0:
                        click.secho(f"  ... {dataset_count} datasets processed", fg="blue")
                        sys.stdout.flush()

                    _migrate_dataset(
                        dga_pkg=dga_pkg,
                        dv_org_id=dv_org_id,
                        dv_org_email=dv_org_email,
                        org_slug=slug,
                        writer=writer,
                        counters=counters,
                        max_filesize_bytes=max_filesize_bytes,
                    )

                click.secho(
                    f"  {slug}: {dataset_count} dataset(s) processed",
                    fg="green",
                )
                sys.stdout.flush()
    finally:
        report_fh.close()

    # ---- Summary ------------------------------------------------------------
    click.secho("\n=== Migration complete ===", fg="cyan", bold=True)
    click.secho(f"  Orgs created:       {counters['org_created']}", fg="green")
    click.secho(f"  Orgs skipped:       {counters['org_skipped']}", fg="yellow")
    click.secho(f"  Orgs failed:        {counters['org_failed']}",
                fg="red" if counters["org_failed"] else "green")
    click.secho(f"  Datasets created:   {counters['dataset_created']}", fg="green")
    click.secho(f"  Datasets skipped:   {counters['dataset_skipped']}", fg="yellow")
    click.secho(f"  Datasets failed:    {counters['dataset_failed']}",
                fg="red" if counters["dataset_failed"] else "green")
    click.secho(f"  Resources uploaded: {counters['resource_uploaded']}", fg="green")
    click.secho(f"  Resources linked:   {counters['resource_linked']}", fg="green")
    click.secho(f"  Resources failed:   {counters['resource_failed']}",
                fg="red" if counters["resource_failed"] else "green")
    click.secho(f"\nAudit report: {report_path}", fg="green")
    sys.stdout.flush()
