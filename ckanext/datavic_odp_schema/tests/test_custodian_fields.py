import pytest

import ckan.model as model
import ckan.plugins.toolkit as tk

CUSTODIAN_FIELDS = ("maintainer_email", "data_owner")

_DATA_OWNER = "Data Custodian Team"
_MAINTAINER_EMAIL = "custodian@example.vic.gov.au"


def _sysadmin_context():
    user = tk.get_action("get_site_user")({"ignore_auth": True}, {})
    return {"user": user["name"], "ignore_auth": True}


def _api_context():
    ctx = _sysadmin_context()
    ctx["api_version"] = 3
    return ctx


@pytest.fixture
def custodian_dataset(dataset_factory):
    return dataset_factory(
        contact_point="contact@example.vic.gov.au",
        data_owner=_DATA_OWNER,
        maintainer_email=_MAINTAINER_EMAIL,
    )


@pytest.mark.usefixtures("clean_db", "clean_index")
class TestCustodianFieldStripping:
    def test_package_show_strips_on_api_request(self, custodian_dataset):
        result = tk.get_action("package_show")(
            _api_context(), {"id": custodian_dataset["id"]}
        )
        for field in CUSTODIAN_FIELDS:
            assert field not in result

    def test_package_show_keeps_fields_for_internal_call(self, custodian_dataset):
        result = tk.get_action("package_show")(
            _sysadmin_context(), {"id": custodian_dataset["id"]}
        )
        assert result["data_owner"] == _DATA_OWNER
        assert result["maintainer_email"] == _MAINTAINER_EMAIL

    def test_package_patch_preserves_custodian_fields(self, custodian_dataset):
        tk.get_action("package_patch")(
            _api_context(),
            {"id": custodian_dataset["id"], "notes": "patched via api"},
        )

        result = tk.get_action("package_show")(
            _sysadmin_context(), {"id": custodian_dataset["id"]}
        )
        assert result["notes"] == "patched via api"
        assert result["data_owner"] == _DATA_OWNER
        assert result["maintainer_email"] == _MAINTAINER_EMAIL

    def test_package_update_preserves_custodian_fields(self, custodian_dataset):
        pkg = tk.get_action("package_show")(
            _sysadmin_context(), {"id": custodian_dataset["id"]}
        )
        pkg["notes"] = "updated via api"

        tk.get_action("package_update")(_api_context(), pkg)

        result = tk.get_action("package_show")(
            _sysadmin_context(), {"id": custodian_dataset["id"]}
        )
        assert result["notes"] == "updated via api"
        assert result["data_owner"] == _DATA_OWNER
        assert result["maintainer_email"] == _MAINTAINER_EMAIL

    def test_resource_patch_preserves_custodian_fields(self, custodian_dataset):
        resource = tk.get_action("resource_create")(
            _sysadmin_context(),
            {
                "package_id": custodian_dataset["id"],
                "url": "http://example.com/data.csv",
                "name": "Test resource",
            },
        )

        tk.get_action("resource_patch")(
            _api_context(),
            {"id": resource["id"], "name": "Renamed resource"},
        )

        result = tk.get_action("package_show")(
            _sysadmin_context(), {"id": custodian_dataset["id"]}
        )
        assert result["resources"][0]["name"] == "Renamed resource"
        assert result["data_owner"] == _DATA_OWNER
        assert result["maintainer_email"] == _MAINTAINER_EMAIL

    def test_resource_update_preserves_custodian_fields(self, custodian_dataset):
        resource = tk.get_action("resource_create")(
            _sysadmin_context(),
            {
                "package_id": custodian_dataset["id"],
                "url": "http://example.com/data.csv",
                "name": "Test resource",
            },
        )

        resource["name"] = "Updated resource"
        tk.get_action("resource_update")(_api_context(), resource)

        result = tk.get_action("package_show")(
            _sysadmin_context(), {"id": custodian_dataset["id"]}
        )
        assert result["resources"][0]["name"] == "Updated resource"
        assert result["data_owner"] == _DATA_OWNER
        assert result["maintainer_email"] == _MAINTAINER_EMAIL

    def test_package_search_strips_on_api_request(self, custodian_dataset):
        session = model.Session()
        session._context = {"api_version": 3}
        try:
            result = tk.get_action("package_search")(
                _sysadmin_context(), {"q": custodian_dataset["name"]}
            )
        finally:
            session._context = None

        assert result["count"] >= 1
        for pkg in result["results"]:
            for field in CUSTODIAN_FIELDS:
                assert field not in pkg

    def test_package_search_keeps_fields_for_internal_call(self, custodian_dataset):
        session = model.Session()
        session._context = None
        result = tk.get_action("package_search")(
            _sysadmin_context(), {"q": custodian_dataset["name"]}
        )

        assert result["count"] >= 1
        match = next(
            pkg for pkg in result["results"] if pkg["id"] == custodian_dataset["id"]
        )
        assert match["data_owner"] == _DATA_OWNER
        assert match["maintainer_email"] == _MAINTAINER_EMAIL
