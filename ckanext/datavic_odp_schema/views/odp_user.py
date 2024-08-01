import logging

from flask import Blueprint

import ckan.lib.captcha as captcha
import ckan.plugins.toolkit as tk
import ckan.views.user as user

from ckan.common import _, request


log = logging.getLogger(__name__)
odp_user = Blueprint("odp_user", __name__)

recaptcha_actions = ["login", "request_reset"]


@odp_user.before_request
def before_request() -> None:
    controller, action = tk.get_endpoint()
    if request.method == "POST" and action in recaptcha_actions:
        try:
            captcha.check_recaptcha(request)
        except captcha.CaptchaError:
            error_msg = _(u'Bad Captcha. Please try again.')
            tk.h.flash_error(error_msg)
            return tk.redirect_to(tk.request.url)


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
