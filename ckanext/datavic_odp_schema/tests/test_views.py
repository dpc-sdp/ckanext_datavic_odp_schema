import pytest

from ckan.lib.helpers import url_for


@pytest.mark.usefixtures("with_request_context")
class TestSitemap(object):
    @pytest.mark.usefixtures("clean_db")
    def test_sitemap_empty(self, app):
        response = app.get(
            url_for("sitemap.index"), environ_overrides={"REMOTE_USER": ""}
        )
        assert response.body == (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n</urlset>'
        )

    def test_sitemap_by_url(self, app):
        response = app.get("/sitemap", environ_overrides={"REMOTE_USER": ""})
        assert "sitemaps" in response.body

        response = app.get("/sitemap.xml", environ_overrides={"REMOTE_USER": ""})
        assert "sitemaps" in response.body

    @pytest.mark.usefixtures("clean_db")
    def test_sitemap_with_data(self, app, dataset, organization, group):
        response = app.get("/sitemap", environ_overrides={"REMOTE_USER": ""})

        assert f"dataset/{dataset['name']}" in response.body
        assert f"organization/{organization['name']}" in response.body
        assert f"group/{group['name']}" in response.body
