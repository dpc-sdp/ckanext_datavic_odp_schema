import factory
import pytest
from faker import Faker
from pytest_factoryboy import register

import ckan.tests.factories as factories

faker = Faker()


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


register(DatasetFactory, "dataset")


class GroupFactory(factories.Group):
    pass


register(GroupFactory, "group")


class OrganizationFactory(factories.Organization):
    pass


register(OrganizationFactory, "organization")
