import factory
import pytest
from faker import Faker
from pytest_factoryboy import register

import ckan.plugins.toolkit as tk
import ckan.tests.factories as factories

faker = Faker()

_CATEGORY_ID = "9ca71dfb-b758-4901-97ba-08cebe923158"


def _ensure_category_group() -> str:
    """Create the DV category group if it doesn't exist, then return its id.

    Used by ``DatasetFactory`` so that any test creating a dataset via the
    factory automatically satisfies the ``choices_helper: category_list``
    validator on the ``category`` field.
    """
    try:
        tk.get_action("group_show")({"ignore_auth": True}, {"id": _CATEGORY_ID})
    except tk.ObjectNotFound:
        site_user = tk.get_action("get_site_user")({"ignore_auth": True}, {})
        ctx = {"ignore_auth": True, "user": site_user["name"]}
        tk.get_action("group_create")(ctx, {
            "id": _CATEGORY_ID,
            "name": "data-themes",
            "title": "Data Themes",
        })
    return _CATEGORY_ID


@pytest.fixture(autouse=True)
def load_standard_plugins(with_plugins):
    """Ensure all plugins listed in ckan.plugins (test.ini) are loaded for every test.

    CKAN's pytest plugin calls ``plugins.unload_non_system_plugins()`` before
    the test run, so non-system plugins must be explicitly reloaded.  The
    ``with_plugins`` fixture handles both load (at test start) and cleanup (at
    test end).
    """


class DatasetFactory(factories.Dataset):
    date_created_data_asset = factory.LazyAttribute(lambda _: faker.date())
    license_id = "other-open"
    category = factory.LazyAttribute(lambda _: _ensure_category_group())
    extract = "Test extract."
    personal_information = "no"
    update_frequency = "monthly"


register(DatasetFactory, "dataset")


class GroupFactory(factories.Group):
    pass


register(GroupFactory, "group")


class OrganizationFactory(factories.Organization):
    pass


register(OrganizationFactory, "organization")
