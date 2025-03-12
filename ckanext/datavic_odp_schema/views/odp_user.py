import logging

from flask import Blueprint

import ckan.lib.captcha as captcha
import ckan.plugins.toolkit as tk
import ckan.lib.navl.dictization_functions as dictization_functions

from ckan import plugins, logic, model, authz
from ckan.views.user import RequestResetView, RegisterView, login, rotate_token


log = logging.getLogger(__name__)
odp_user = Blueprint("odp_user", __name__)

recaptcha_actions = ["login", "request_reset", "register"]
CAPTCHA_ERROR_MESSAGE = "CAPTCHA verification failed. Please try again."


class ODPRegisterView(RegisterView):
    """Custom registration view that skips the recaptcha check.

    We override the post method to avoid duplicate recaptcha verification since
    it's already checked in the before_request hook. This prevents the
    'timeout-or-duplicate' error that occurs when recaptcha is verified twice.
    """
    def post(self):
        context = self._prepare()
        try:
            data_dict = logic.clean_dict(
                dictization_functions.unflatten(
                    logic.tuplize_dict(logic.parse_params(tk.request.form))))
            data_dict.update(logic.clean_dict(
                dictization_functions.unflatten(
                    logic.tuplize_dict(logic.parse_params(tk.request.files)))
            ))

        except dictization_functions.DataError:
            tk.abort(400, tk._(u'Integrity Error'))

        try:
            user_dict = logic.get_action(u'user_create')(context, data_dict)
        except logic.NotAuthorized:
            tk.abort(403, tk._(u'Unauthorized to create user %s') % u'')
        except logic.NotFound:
            tk.abort(404, tk._(u'User not found'))
        except logic.ValidationError as e:
            errors = e.error_dict
            error_summary = e.error_summary
            return self.get(data_dict, errors, error_summary)

        user = tk.current_user.name
        if user:
            # #1799 User has managed to register whilst logged in - warn user
            # they are not re-logged in as new user.
            tk.h.flash_success(
                tk._(u'User "%s" is now registered but you are still '
                  u'logged in as "%s" from before') % (data_dict[u'name'],
                                                       user))
            if authz.is_sysadmin(user):
                # the sysadmin created a new user. We redirect him to the
                # activity page for the newly created user
                if "activity" in tk.g.plugins:
                    return tk.redirect_to(
                        u'activity.user_activity', id=data_dict[u'name'])
                return tk.redirect_to(u'user.read', id=data_dict[u'name'])
            else:
                return tk.render(u'user/logout_first.html')

        # log the user in programatically
        userobj = model.User.get(user_dict["id"])
        if userobj:
            tk.login_user(userobj)
            rotate_token()

        resp = tk.redirect_to(u'user.me')
        return resp


@odp_user.before_request
def before_request() -> None:
    _, action = tk.get_endpoint()

    # Skip recaptcha check if 2FA is enabled, it will be checked with ckanext-auth
    if plugins.plugin_loaded("auth") and tk.h.is_2fa_enabled() and action == "login":
        return

    if tk.request.method == "POST" and action in recaptcha_actions:
        try:
            captcha.check_recaptcha(tk.request)
        except captcha.CaptchaError:
            error_msg = tk._(CAPTCHA_ERROR_MESSAGE)
            tk.h.flash_error(error_msg)
            return tk.h.redirect_to(tk.request.url)


def register_odp_user_plugin_rules(blueprint):
    blueprint.add_url_rule(
        "/user/reset",
        view_func=RequestResetView.as_view(str("request_reset"))
    )
    blueprint.add_url_rule(
        "/user/login",
        view_func=login, methods=("GET", "POST")
    )
    blueprint.add_url_rule(
        "/user/register", view_func=ODPRegisterView.as_view(str(u'register'))
    )


register_odp_user_plugin_rules(odp_user)
