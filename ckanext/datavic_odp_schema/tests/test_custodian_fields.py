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


def _sysadmin_api_context():
    return _api_context()


def _normal_api_context(user):
    return {"user": user["name"], "api_version": 3}


def _anonymous_api_context():
    return {"user": "", "api_version": 3}


@pytest.fixture
def normal_user(user_factory):
    return user_factory()


@pytest.fixture
def custodian_dataset(dataset_factory):
    return dataset_factory(
        contact_point="contact@example.vic.gov.au",
        data_owner=_DATA_OWNER,
        maintainer_email=_MAINTAINER_EMAIL,
    )


@pytest.mark.usefixtures("clean_db", "clean_index")
class TestCustodianFieldStripping:
    # --- package_show -------------------------------------------------------

    def test_package_show_strips_both_for_normal_user(
        self, custodian_dataset, normal_user
    ):
        result = tk.get_action("package_show")(
            _normal_api_context(normal_user), {"id": custodian_dataset["id"]}
        )
        assert "maintainer_email" not in result
        assert "data_owner" not in result

    def test_package_show_strips_both_for_anonymous_api_request(
        self, custodian_dataset
    ):
        result = tk.get_action("package_show")(
            _anonymous_api_context(), {"id": custodian_dataset["id"]}
        )
        assert "maintainer_email" not in result
        assert "data_owner" not in result

    def test_package_show_sysadmin_keeps_data_owner_strips_maintainer_email(
        self, custodian_dataset
    ):
        result = tk.get_action("package_show")(
            _sysadmin_api_context(), {"id": custodian_dataset["id"]}
        )
        # data_owner retained for sysadmin (required field for the DD harvest)
        assert result["data_owner"] == _DATA_OWNER
        # maintainer_email always stripped from the API, even for sysadmins
        assert "maintainer_email" not in result

    def test_package_show_keeps_both_for_internal_call(self, custodian_dataset):
        result = tk.get_action("package_show")(
            _sysadmin_context(), {"id": custodian_dataset["id"]}
        )
        assert result["data_owner"] == _DATA_OWNER
        assert result["maintainer_email"] == _MAINTAINER_EMAIL

    # --- write paths preserve the stored values -----------------------------

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

    # --- package_search -----------------------------------------------------
    #
    # after_dataset_search has no action context; it reads the request user from
    # the CKAN-stashed Session._context (set by ckan/views/api.py). Tests stash
    # {"user": <name>, "api_version": 3} to mimic that — no tk.current_user.

    def _search_with_stashed_context(self, stashed_context, query_context, query):
        session = model.Session()
        session._context = stashed_context
        try:
            return tk.get_action("package_search")(query_context, {"q": query})
        finally:
            session._context = None

    def test_package_search_strips_both_for_normal_user(
        self, custodian_dataset, normal_user
    ):
        result = self._search_with_stashed_context(
            {"user": normal_user["name"], "api_version": 3},
            _normal_api_context(normal_user),
            custodian_dataset["name"],
        )

        assert result["count"] >= 1
        for pkg in result["results"]:
            assert "maintainer_email" not in pkg
            assert "data_owner" not in pkg

    def test_package_search_strips_both_for_anonymous_api_request(
        self, custodian_dataset
    ):
        result = self._search_with_stashed_context(
            {"user": "", "api_version": 3},
            _anonymous_api_context(),
            custodian_dataset["name"],
        )

        assert result["count"] >= 1
        for pkg in result["results"]:
            assert "maintainer_email" not in pkg
            assert "data_owner" not in pkg

    def test_package_search_sysadmin_keeps_data_owner_strips_maintainer_email(
        self, custodian_dataset
    ):
        sysadmin_name = tk.get_action("get_site_user")({"ignore_auth": True}, {})[
            "name"
        ]
        result = self._search_with_stashed_context(
            {"user": sysadmin_name, "api_version": 3},
            _sysadmin_context(),
            custodian_dataset["name"],
        )

        assert result["count"] >= 1
        match = next(
            pkg for pkg in result["results"] if pkg["id"] == custodian_dataset["id"]
        )
        assert match["data_owner"] == _DATA_OWNER
        assert "maintainer_email" not in match

    def test_package_search_keeps_both_for_internal_call(self, custodian_dataset):
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
