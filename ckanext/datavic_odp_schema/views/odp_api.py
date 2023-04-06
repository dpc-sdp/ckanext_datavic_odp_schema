import logging

from flask import Blueprint

import ckan.views.api as api

import ckanext.datavic_odp_schema.const as const


log = logging.getLogger(__name__)

odp_api = Blueprint('odp_api', __name__)


def odp_api_i18n_js_translations(lang:str, ver:int=api.API_REST_DEFAULT_VERSION):
    """Map the custom lang code to ckan version of lang code.

    
    Args:
        lang (str): language code
        ver (int): api version 
    
    
    Returns:
        dict: if passed a valid lang code
    """

    if lang in const.DATAVIC_CKAN_I18N_MAPPER:
        lang = const.DATAVIC_CKAN_I18N_MAPPER[lang]

    return api.i18n_js_translations(lang, ver)


def register_odp_api_plugin_rules(blueprint):
    blueprint.add_url_rule('/api/i18n/<lang>', view_func=odp_api_i18n_js_translations)

register_odp_api_plugin_rules(odp_api)