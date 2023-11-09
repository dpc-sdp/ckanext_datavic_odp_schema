import pytest
from faker import Faker

import ckan.plugins.toolkit as tk

from ckanext.datavic_odp_schema.helpers import date_str_to_timestamp


fake = Faker()


@pytest.fixture
def resource_data():
    def func(**kwargs):
        data_dict = {
            "id": fake.uuid4(),
            "url": fake.url(),
            "name": fake.slug(fake.sentence(nb_words=5)),
            "format": "csv",
        }
        data_dict.update(kwargs)
        return data_dict

    return func


class TestHelpers:
    @pytest.mark.usefixtures("clean_db")
    def test_resource_formats_list(self, dataset_factory, resource_data):
        dataset_factory(
            resources=[
                resource_data(),
                resource_data(),
                resource_data(format="xml"),
                resource_data(format=""),
            ]
        )

        format_list: list[str] = tk.h.format_list()
        assert format_list == ["CSV", "XML"]

    @pytest.mark.usefixtures("clean_db")
    def test_resource_formats_list_no_resources(self):
        assert not tk.h.format_list()

    def test_date_str_to_timestamp(self):
        """Date parser func shouldn't throw exceptions"""
        assert date_str_to_timestamp("2023-01-05")
        assert date_str_to_timestamp("2023-02-07T13:19:10.373545")
        assert not date_str_to_timestamp("")
        assert not date_str_to_timestamp(None)
        assert not date_str_to_timestamp((1,1))

    def test_is_other_license(self):
        assert not tk.h.is_other_license({})
        assert not tk.h.is_other_license({"license_id": ""})
        assert not tk.h.is_other_license({"license_id": "cc-by"})
        assert tk.h.is_other_license({"license_id": "other"})
        assert tk.h.is_other_license({"license_id": "other-open"})
