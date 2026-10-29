import pytest
from bs4 import BeautifulSoup

import ckan.plugins.toolkit as tk
import ckan.tests.factories as factories
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


@pytest.mark.usefixtures("clean_db")
@pytest.mark.ckan_config("WTF_CSRF_ENABLED", True)
class TestODPUserCSRF:
    endpoints = ["odp_user.login", "odp_user.register", "odp_user.request_reset"]
    forms = {
        "odp_user.login": {"login": "a", "password": "b"},
        "odp_user.register": {
            "name": "csrf-probe", "email": "csrf-probe@example.com",
            "password1": "Csrf-Probe-2117", "password2": "Csrf-Probe-2117",
        },
        "odp_user.request_reset": {"user": "a"},
    }

    @pytest.mark.parametrize("endpoint", endpoints)
    def test_post_without_csrf_token_is_rejected(self, app, endpoint):
        app.post(url_for(endpoint), data=self.forms[endpoint], status=400)

    @pytest.mark.ckan_config("ckan.auth.create_user_via_web", True)
    @pytest.mark.parametrize("endpoint, expected", [
        ("odp_user.login", 200),  # bad credentials re-render the form
        ("odp_user.register", 302),  # account created, redirect to user.me
        ("odp_user.request_reset", 302),
    ])
    def test_post_with_csrf_token_is_processed(self, app, endpoint, expected):
        client = app.test_client()
        page = client.get(url_for(endpoint))
        token = BeautifulSoup(page.data, "html.parser").select_one(
            "input[name=_csrf_token]"
        )["value"]

        response = client.post(
            url_for(endpoint), data={**self.forms[endpoint], "_csrf_token": token}, follow_redirects=False
        )

        assert response.status_code == expected

    @pytest.mark.parametrize("endpoint", endpoints)
    def test_post_with_api_token_but_no_csrf_token_is_rejected(self, app, endpoint):
        token = factories.APIToken(user=factories.User()["name"])["token"]
        headers = {tk.config.get("apitoken_header_name"): token}

        app.post(url_for(endpoint), data=self.forms[endpoint], headers=headers, status=400)

    @pytest.mark.ckan_config("ckan.cache_enabled", True)
    @pytest.mark.parametrize("endpoint", endpoints)
    def test_page_is_not_publicly_cached(self, app, endpoint):
        response = app.get(url_for(endpoint))

        assert "private" in response.headers["Cache-Control"]
