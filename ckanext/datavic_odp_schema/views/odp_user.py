import logging

from flask import Blueprint

from ckan import plugins
import ckan.lib.captcha as captcha
import ckan.plugins.toolkit as tk
import ckan.views.user as user


log = logging.getLogger(__name__)
odp_user = Blueprint("odp_user", __name__)

recaptcha_actions = ["login", "request_reset"]


@odp_user.before_request
def before_request() -> None:
    _, action = tk.get_endpoint()

    # Skip recaptcha check if 2FA is enabled, it will be checked with ckanext-auth
    if plugins.plugin_loaded("auth") and tk.h.is_2fa_enabled():
        return;

    if tk.request.method == "POST" and action in recaptcha_actions:
        try:
            captcha.check_recaptcha(tk.request)
        except captcha.CaptchaError:
            error_msg = tk._('Bad Captcha. Please try again.')
            tk.h.flash_error(error_msg)
            return tk.h.redirect_to(tk.request.url)


def register_odp_user_plugin_rules(blueprint):
    blueprint.add_url_rule(
        "/user/reset",
        view_func=user.RequestResetView.as_view(str("request_reset"))
    )
    blueprint.add_url_rule(
        "/user/login",
        view_func=user.login, methods=("GET", "POST")
    )


register_odp_user_plugin_rules(odp_user)
