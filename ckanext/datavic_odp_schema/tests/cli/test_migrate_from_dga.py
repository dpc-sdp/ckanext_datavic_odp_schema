"""Tests for the data.gov.au → DataVic council migration command.

Unit tests exercise the pure-Python mapping helpers without a CKAN stack.
Integration tests use a CKAN test database (``clean_db`` fixture) and
monkeypatch ``ckanapi.RemoteCKAN`` so no real DGA network calls are made.
"""

from __future__ import annotations

import csv
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ckanext.datavic_odp_schema.cli.migrate_from_dga import (
    LICENSE_FALLBACK,
    FREQUENCY_FALLBACK,
    TAG_FALLBACK,
    _load_councils,
    _map_frequency,
    _map_license,
    _tag_string,
    _build_dataset_payload,
    _resource_name,
)


# ---------------------------------------------------------------------------
# Unit — license mapping
# ---------------------------------------------------------------------------


class TestLicenseMap:
    """Every DGA license_id in the ticket table must map to the correct DV value."""

    @pytest.mark.parametrize(
        "dga_id, expected_dv, expect_flag",
        [
            ("cc-by", "cc-by", ""),
            ("cc-by-2.5", "cc-by", ""),
            ("cc-by-4.0", "cc-by", ""),
            ("cc-by-sa", "cc-by-sa", ""),
            ("cc-nc", "cc-nc", ""),
            ("other-nc", "cc-nc", ""),
            ("other", "other", ""),
            ("other-open", "other", ""),
            ("other-forsale", "other", "license_unmapped"),
            ("other-unpublished", "other", "license_unmapped"),
            ("pdm", "other", "license_unmapped"),
            ("oecd-data", "other", "license_unmapped"),
            # Fallback cases
            ("notspecified", LICENSE_FALLBACK, "license_fallback"),
            ("", LICENSE_FALLBACK, "license_fallback"),
        ],
    )
    def test_license_map(self, dga_id: str, expected_dv: str, expect_flag: str) -> None:
        dv_license, flag = _map_license(dga_id)
        assert dv_license == expected_dv, f"{dga_id!r} → expected {expected_dv!r}, got {dv_license!r}"
        assert flag == expect_flag, f"{dga_id!r} → expected flag {expect_flag!r}, got {flag!r}"


# ---------------------------------------------------------------------------
# Unit — update-frequency mapping
# ---------------------------------------------------------------------------


class TestFrequencyMap:
    """Frequency values must use schema enum casing (asNeeded, notPlanned)."""

    @pytest.mark.parametrize(
        "dga_val, expected_dv, expect_flag",
        [
            ("daily", "daily", ""),
            ("weekly", "weekly", ""),
            ("monthly", "monthly", ""),
            ("quarterly", "quarterly", ""),
            ("biannually", "biannually", ""),
            ("annually", "annually", ""),
            ("biennaully", "biannually", ""),   # DGA typo — maps to biannually
            ("infrequently", "irregular", ""),
            ("never", "notPlanned", ""),         # schema casing: notPlanned not notplanned
            ("other", "unknown", ""),
            ("", FREQUENCY_FALLBACK, "freq_fallback"),
        ],
    )
    def test_frequency_map(self, dga_val: str, expected_dv: str, expect_flag: str) -> None:
        pkg = {"extras": [{"key": "update_freq", "value": dga_val}]} if dga_val else {}
        dv_val, flag = _map_frequency(pkg)
        assert dv_val == expected_dv, f"{dga_val!r} → expected {expected_dv!r}, got {dv_val!r}"
        assert flag == expect_flag

    def test_frequency_absent_extra(self) -> None:
        """When update_freq extra is absent the fallback is 'unknown'."""
        dv_val, flag = _map_frequency({"extras": []})
        assert dv_val == FREQUENCY_FALLBACK
        assert flag == "freq_fallback"

    def test_frequency_no_extras_key(self) -> None:
        """When the package has no extras at all the fallback is 'unknown'."""
        dv_val, flag = _map_frequency({})
        assert dv_val == FREQUENCY_FALLBACK
        assert flag == "freq_fallback"


# ---------------------------------------------------------------------------
# Unit — dataset field mapper
# ---------------------------------------------------------------------------


class TestBuildDatasetPayload:
    def _dga_pkg(self, **overrides) -> dict:
        pkg: dict[str, Any] = {
            "id": "dga-uuid-1234",
            "name": "my-dataset",
            "title": "My Dataset",
            "notes": "A" * 300,
            "tags": [{"name": "environment"}, {"name": "water"}],
            "license_id": "cc-by",
            "author": "Test Author",
            "contact_point": "test@example.com",
            "extras": [
                {"key": "temporal_coverage_from", "value": "2020-01-01"},
                {"key": "temporal_coverage_to", "value": "2023-12-31"},
                {"key": "update_freq", "value": "monthly"},
            ],
            "resources": [],
        }
        pkg.update(overrides)
        return pkg

    def test_date_created_from_temporal_coverage_from(self) -> None:
        """date_created_data_asset must come from temporal_coverage_from, not metadata_created."""
        pkg = self._dga_pkg(
            extras=[
                {"key": "temporal_coverage_from", "value": "2019-06-01"},
                {"key": "update_freq", "value": "monthly"},
            ]
        )
        payload = _build_dataset_payload(pkg, "org-id-abc", [])
        assert payload["date_created_data_asset"] == "2019-06-01"

    def test_maintainer_email_from_contact_point(self) -> None:
        pkg = self._dga_pkg(contact_point="contact@council.vic.gov.au")
        payload = _build_dataset_payload(pkg, "org-id-abc", [])
        assert payload["maintainer_email"] == "contact@council.vic.gov.au"

    def test_extract_truncated_to_200(self) -> None:
        long_notes = "B" * 500
        pkg = self._dga_pkg(notes=long_notes)
        payload = _build_dataset_payload(pkg, "org-id-abc", [])
        assert payload["extract"] == "B" * 200

    def test_tag_string_joined(self) -> None:
        pkg = self._dga_pkg(tags=[{"name": "flood"}, {"name": "river"}])
        payload = _build_dataset_payload(pkg, "org-id-abc", [])
        assert "flood" in payload["tag_string"]
        assert "river" in payload["tag_string"]

    def test_tag_string_fallback_when_no_tags(self) -> None:
        flags: list[str] = []
        pkg = self._dga_pkg(tags=[])
        payload = _build_dataset_payload(pkg, "org-id-abc", flags)
        assert payload["tag_string"] == TAG_FALLBACK
        assert "tag_fallback" in flags

    def test_fixed_defaults(self) -> None:
        pkg = self._dga_pkg()
        payload = _build_dataset_payload(pkg, "org-id-abc", [])
        assert payload["category"] == "9ca71dfb-b758-4901-97ba-08cebe923158"
        assert payload["personal_information"] == "no"
        assert payload["private"] is False

    def test_full_metadata_url_set(self) -> None:
        pkg = self._dga_pkg(name="alpine-flood-data")
        payload = _build_dataset_payload(pkg, "org-id-abc", [])
        assert payload["full_metadata_url"] == "https://data.gov.au/data/dataset/alpine-flood-data"

    def test_id_preserved(self) -> None:
        pkg = self._dga_pkg(id="preserved-uuid-abc")
        payload = _build_dataset_payload(pkg, "org-id-abc", [])
        assert payload["id"] == "preserved-uuid-abc"

    def test_license_flag_propagated(self) -> None:
        flags: list[str] = []
        pkg = self._dga_pkg(license_id="pdm")
        _build_dataset_payload(pkg, "org-id-abc", flags)
        assert "license_unmapped" in flags


# ---------------------------------------------------------------------------
# Unit — tag_string helper
# ---------------------------------------------------------------------------


class TestTagString:
    def test_tags_joined(self) -> None:
        pkg = {"tags": [{"name": "alpha"}, {"name": "beta"}]}
        result, flag = _tag_string(pkg)
        assert "alpha" in result
        assert "beta" in result
        assert flag == ""

    def test_empty_tags_uses_fallback(self) -> None:
        result, flag = _tag_string({"tags": []})
        assert result == TAG_FALLBACK
        assert flag == "tag_fallback"

    def test_missing_tags_key_uses_fallback(self) -> None:
        result, flag = _tag_string({})
        assert result == TAG_FALLBACK
        assert flag == "tag_fallback"


# ---------------------------------------------------------------------------
# Unit — resource name helper
# ---------------------------------------------------------------------------


class TestResourceName:
    def test_uses_name_when_present(self) -> None:
        assert _resource_name({"name": "My File", "url": "http://x.com/a.csv"}) == "My File"

    def test_falls_back_to_url_basename(self) -> None:
        assert _resource_name({"name": "", "url": "https://example.com/data/flood.csv"}) == "flood.csv"

    def test_falls_back_to_literal_resource_when_basename_empty(self) -> None:
        assert _resource_name({"name": "", "url": "https://example.com/"}) == "resource"


# ---------------------------------------------------------------------------
# Unit — CSV loader
# ---------------------------------------------------------------------------


class TestLoadCouncils:
    def test_loads_clean_csv(self, tmp_path) -> None:
        csv_file = tmp_path / "councils.csv"
        csv_file.write_text(
            "Organisation,URL,Org Slug\nAlpine Shire Council,https://data.gov.au/data/organization/alpine-shire-council,alpine-shire-council\n",
            encoding="utf-8",
        )
        councils = _load_councils(str(csv_file))
        assert len(councils) == 1
        assert councils[0]["Org Slug"] == "alpine-shire-council"

    def test_strips_nbsp_padding(self, tmp_path) -> None:
        """NBSP (\\u00a0) padding on all cells must be stripped."""
        csv_file = tmp_path / "councils_nbsp.csv"
        # Simulate the NBSP-padded source file
        content = (
            "Organisation\u00a0,URL\u00a0,Org Slug\u00a0\n"
            "Alpine\u00a0,https://data.gov.au\u00a0,alpine-shire-council\u00a0\n"
        )
        csv_file.write_text(content, encoding="utf-8")
        councils = _load_councils(str(csv_file))
        assert councils[0]["Org Slug"] == "alpine-shire-council"
        assert councils[0]["Organisation"] == "Alpine"

    def test_strips_bom(self, tmp_path) -> None:
        """UTF-8 BOM must not appear in column names."""
        csv_file = tmp_path / "councils_bom.csv"
        csv_file.write_bytes(
            b"\xef\xbb\xbfOrganisation,URL,Org Slug\nTest,http://x.com,test-slug\n"
        )
        councils = _load_councils(str(csv_file))
        assert "Org Slug" in councils[0]
        assert councils[0]["Org Slug"] == "test-slug"

    def test_all_39_councils_in_bundled_csv(self) -> None:
        """Bundled CSV must have exactly 39 council rows with non-empty slugs."""
        # Relative path works on the host (6 levels up from tests/cli/ reaches
        # datavic_ckan_odp_lagoon/).
        bundled = os.path.normpath(os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..", "..", "..", "..",
            "etc", "default", "vic-councils.csv",
        ))
        if not os.path.exists(bundled):
            # In the container the CSV is installed at this fixed path by the
            # Dockerfile (COPY etc/default/* /app/ckan/default/).
            bundled = "/app/ckan/default/vic-councils.csv"
        if not os.path.exists(bundled):
            pytest.skip(f"Bundled CSV not found at {bundled!r}")
        councils = _load_councils(bundled)
        assert len(councils) == 39
        for c in councils:
            assert c.get("Org Slug"), f"Missing slug in row: {c}"


# ---------------------------------------------------------------------------
# Integration — CLI command with mocked DGA + real CKAN DB
# ---------------------------------------------------------------------------


# Valid UUIDs required — CKAN rejects non-UUID id values in create actions.
DGA_ORG_ID = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
DGA_PKG_ID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
DGA_RES_LINK_ID = "6ba7b811-9dad-11d1-80b4-00c04fd430c8"
DGA_RES_UPLOAD_ID = "6ba7b812-9dad-11d1-80b4-00c04fd430c8"


def _make_dga_org(slug: str = "test-council") -> dict:
    return {
        "id": DGA_ORG_ID,
        "name": slug,
        "title": "Test Council",
        "description": "A test council.",
        "image_display_url": "",
    }


def _make_dga_package(org_id: str = DGA_ORG_ID) -> dict:
    return {
        "id": DGA_PKG_ID,
        "name": "test-flood-data",
        "title": "Test Flood Data",
        "notes": "Flood data from Test Council.",
        "tags": [{"name": "flood"}],
        "license_id": "cc-by",
        "author": "Test Author",
        "contact_point": "floods@test.vic.gov.au",
        "extras": [
            {"key": "temporal_coverage_from", "value": "2021-01-01"},
            {"key": "temporal_coverage_to", "value": "2023-12-31"},
            {"key": "update_freq", "value": "annually"},
        ],
        "resources": [
            {
                "id": DGA_RES_LINK_ID,
                "name": "Flood Map",
                "url": "https://example.com/flood.pdf",
                "url_type": "",
                "format": "PDF",
                "description": "A flood map.",
                "size": None,
                "created": "2022-03-15T00:00:00",
            },
            {
                "id": DGA_RES_UPLOAD_ID,
                "name": "Raw Data",
                "url": "https://data.gov.au/dataset/test/resource/dga-res-uuid-upload/download/data.csv",
                "url_type": "upload",
                "format": "CSV",
                "description": "",
                "size": 1024,
                "created": "2022-04-01T00:00:00",
            },
        ],
    }


class TestMigrateCommand:
    """Integration tests: monkeypatched DGA, real CKAN DB via clean_db."""

    @pytest.fixture
    def category_group(self, clean_db):
        """Create the fixed category group required by the DV schema.

        The ``category`` field uses ``choices_helper: category_list`` which
        reads CKAN groups from the DB.  The migration hard-codes category UUID
        ``9ca71dfb-...``.  Without this group in the DB the scheming select
        validator rejects the value as 'unexpected choice'.

        Depends on ``clean_db`` to guarantee it runs after the DB is reset.
        """
        import ckan.plugins.toolkit as tk
        site_user = tk.get_action("get_site_user")({"ignore_auth": True}, {})
        ctx = {"ignore_auth": True, "user": site_user["name"]}
        tk.get_action("group_create")(ctx, {
            "id": "9ca71dfb-b758-4901-97ba-08cebe923158",
            "name": "data-themes",
            "title": "Data Themes",
        })

    @pytest.fixture
    def csv_path(self, tmp_path) -> str:
        p = tmp_path / "councils.csv"
        p.write_text(
            "Organisation,URL,Org Slug\n"
            "Test Council,https://data.gov.au/data/organization/test-council,test-council\n",
            encoding="utf-8",
        )
        return str(p)

    @pytest.fixture
    def mock_dga(self):
        """Monkeypatch ckanapi.RemoteCKAN to return one org + one dataset."""
        dga_org = _make_dga_org()
        dga_pkg = _make_dga_package()

        mock_client = MagicMock()
        mock_client.action.organization_show.return_value = dga_org
        # iter_org_packages uses package_search — wire up both
        mock_client.action.package_search.return_value = {
            "count": 1,
            "results": [dga_pkg],
        }

        with patch(
            "ckanext.datavic_odp_schema.cli.dga_client.ckanapi.RemoteCKAN",
            return_value=mock_client,
        ):
            yield mock_client, dga_org, dga_pkg

    @pytest.mark.usefixtures("category_group")
    def test_first_run_creates_org_and_dataset(
        self, mock_dga, csv_path, tmp_path
    ) -> None:
        from click.testing import CliRunner
        from ckanext.datavic_odp_schema.cli.migrate_from_dga import migrate_from_data_gov_au
        import ckan.plugins.toolkit as tk

        _, dga_org, dga_pkg = mock_dga

        # Patch resource uploads: the upload resource will try to download from DGA.
        # Patch download_file to write a small dummy file.
        def fake_download(url, dest_path, max_bytes):
            with open(dest_path, "wb") as f:
                f.write(b"CSV,DATA\n1,2\n")
            return 14

        with patch(
            "ckanext.datavic_odp_schema.cli.migrate_from_dga.dga.download_file",
            side_effect=fake_download,
        ), patch(
            "ckanext.datavic_odp_schema.cli.migrate_from_dga.dga.head_size",
            return_value=14,
        ):
            runner = CliRunner()
            result = runner.invoke(
                migrate_from_data_gov_au,
                [
                    "--org", "test-council",
                    "--csv-path", csv_path,
                    "--report-dir", str(tmp_path / "reports"),
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0, result.output
        assert "Datasets failed:    0" in result.output, (
            f"Migration had dataset failures:\n{result.output}"
        )

        # Org created on DV with preserved DGA id
        org = tk.get_action("organization_show")(
            {"ignore_auth": True}, {"id": DGA_ORG_ID}
        )
        assert org["name"] == "test-council"

        # Dataset created with preserved DGA id
        # Use use_cache=False to bypass Solr and read directly from DB so
        # scheming's convert_from_extras always runs (Solr validated_data_dict
        # may be built before the scheming field is promoted to top-level).
        pkg = tk.get_action("package_show")(
            {"ignore_auth": True, "use_cache": False}, {"id": DGA_PKG_ID}
        )
        assert pkg["name"] == "test-flood-data"
        assert pkg["license_id"] == "cc-by"
        assert pkg["maintainer_email"] == "floods@test.vic.gov.au"
        assert pkg.get("date_created_data_asset") == "2021-01-01", (
            f"date_created_data_asset wrong/missing. "
            f"keys={sorted(pkg.keys())}, extras={pkg.get('extras', [])}"
        )
        assert pkg["full_metadata_url"] == "https://data.gov.au/data/dataset/test-flood-data"

        # Both resources created
        assert len(pkg["resources"]) == 2

    @pytest.mark.usefixtures("category_group")
    def test_second_run_skips_existing_dataset(
        self, mock_dga, csv_path, tmp_path
    ) -> None:
        """On re-run, existing DV datasets must be skipped (AC5)."""
        from click.testing import CliRunner
        from ckanext.datavic_odp_schema.cli.migrate_from_dga import migrate_from_data_gov_au

        def fake_download(url, dest_path, max_bytes):
            with open(dest_path, "wb") as f:
                f.write(b"x")
            return 1

        invoke_kwargs = dict(
            args=[
                "--org", "test-council",
                "--csv-path", csv_path,
                "--report-dir", str(tmp_path / "reports"),
            ],
            catch_exceptions=False,
        )
        runner = CliRunner()
        report_dir_1 = str(tmp_path / "reports_run1")
        report_dir_2 = str(tmp_path / "reports_run2")

        with patch(
            "ckanext.datavic_odp_schema.cli.migrate_from_dga.dga.download_file",
            side_effect=fake_download,
        ), patch(
            "ckanext.datavic_odp_schema.cli.migrate_from_dga.dga.head_size",
            return_value=1,
        ):
            # First run — creates the org + dataset
            r1 = runner.invoke(
                migrate_from_data_gov_au,
                args=[
                    "--org", "test-council",
                    "--csv-path", csv_path,
                    "--report-dir", report_dir_1,
                ],
                catch_exceptions=False,
            )
            assert r1.exit_code == 0

            # Second run — dataset must be skipped (uses separate report dir
            # to avoid same-second timestamp collision in the filename)
            r2 = runner.invoke(
                migrate_from_data_gov_au,
                args=[
                    "--org", "test-council",
                    "--csv-path", csv_path,
                    "--report-dir", report_dir_2,
                ],
                catch_exceptions=False,
            )
            assert r2.exit_code == 0

        # Audit CSV from second run must show dataset as skipped
        from pathlib import Path
        csvs2 = sorted(Path(report_dir_2).glob("datagov_migration_*.csv"))
        assert len(csvs2) == 1, f"Expected exactly one report CSV in run-2 dir, got: {csvs2}"

        with open(csvs2[0]) as fh:
            rows = list(csv.DictReader(fh))

        dataset_rows = [r for r in rows if r["stage"] == "dataset"]
        assert all(r["status"] == "skipped" for r in dataset_rows), (
            f"Expected all dataset rows skipped on re-run, got: {dataset_rows}"
        )

    @pytest.mark.usefixtures("category_group")
    def test_over_cap_resource_stored_as_url(
        self, mock_dga, csv_path, tmp_path
    ) -> None:
        """Resources reported as >cap by HEAD must be stored as DGA URLs."""
        from click.testing import CliRunner
        from ckanext.datavic_odp_schema.cli.migrate_from_dga import migrate_from_data_gov_au
        import ckan.plugins.toolkit as tk

        _, _, dga_pkg = mock_dga
        max_mb = 100

        with patch(
            "ckanext.datavic_odp_schema.cli.migrate_from_dga.dga.head_size",
            return_value=(max_mb + 1) * 1024 * 1024,
        ), patch(
            "ckanext.datavic_odp_schema.cli.migrate_from_dga.dga.download_file",
        ) as mock_dl:
            runner = CliRunner()
            result = runner.invoke(
                migrate_from_data_gov_au,
                [
                    "--org", "test-council",
                    "--csv-path", csv_path,
                    "--report-dir", str(tmp_path / "reports"),
                    "--max-filesize-mb", str(max_mb),
                ],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        # download_file must NOT have been called (size check short-circuits it)
        mock_dl.assert_not_called()

        pkg = tk.get_action("package_show")(
            {"ignore_auth": True}, {"id": dga_pkg["id"]}
        )
        upload_res = next(
            (r for r in pkg["resources"] if r.get("name") == "Raw Data"), None
        )
        assert upload_res is not None
        # URL should be the original DGA URL, not a FileStore upload path
        assert upload_res["url"].startswith("https://data.gov.au")


