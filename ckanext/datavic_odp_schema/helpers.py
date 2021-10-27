import os
import re
import pkgutil
import inspect
import logging

import time
import calendar

from flask import Blueprint

import ckan.plugins.toolkit as toolkit


log = logging.getLogger(__name__)


def _register_blueprints():
    u'''Return all blueprints defined in the `views` folder
    '''
    blueprints = []

    def is_blueprint(mm):
        return isinstance(mm, Blueprint)

    path = os.path.join(os.path.dirname(__file__), 'views')

    for loader, name, _ in pkgutil.iter_modules([path]):
        module = loader.find_module(name).load_module(name)
        for blueprint in inspect.getmembers(module, is_blueprint):
            blueprints.append(blueprint[1])
            log.info(u'Registered blueprint: {0!r}'.format(blueprint[0]))
    return blueprints

def historical_resources_list(resource_list):
    sorted_resource_list = {}
    i = 0
    for resource in resource_list:
        i += 1
        if resource.get('period_start') is not None and resource.get('period_start') != 'None' and resource.get(
                'period_start') != '':
            key = _parse_date(resource.get('period_start')[:10]) or '9999999999' + str(i)
        else:
            key = '9999999999' + str(i)
        resource['key'] = key
        # print parser.parse(resource.get('period_start')).strftime("%Y-%M-%d") + " " + resource.get('period_start')
        sorted_resource_list[key] = resource

    list = sorted(sorted_resource_list.values(), key=lambda item: int(item.get('key')), reverse=True)
    # for item in list:
    #    print item.get('period_start') + " " + str(item.get('key'))
    return list

def historical_resources_range(resource_list):
    range_from = ""
    from_ts = None
    range_to = ""
    to_ts = None
    for resource in resource_list:

        if resource.get('period_start') is not None and resource.get('period_start') != 'None' and resource.get(
                'period_start') != '':
            ts = _parse_date(resource.get('period_start')[:10])
            if ts and (from_ts is None or ts < from_ts):
                from_ts = ts
                range_from = resource.get('period_start')[:10]
        if resource.get('period_end') is not None and resource.get('period_end') != 'None' and resource.get(
                'period_end') != '':
            ts = _parse_date(resource.get('period_end')[:10])
            if ts and (to_ts is None or ts > to_ts):
                to_ts = ts
                range_to = resource.get('period_end')[:10]

    pattern = '^(\d{4})-(\d{2})-(\d{2})$'

    if range_from and re.match(pattern, range_from):
        range_from = re.sub(pattern, r'\3/\2/\1', range_from)
    if range_to and re.match(pattern, range_to):
        range_to = re.sub(pattern, r'\3/\2/\1', range_to)

    if range_from != "" and range_to != "":
        return range_from + " to " + range_to
    elif range_from != "" or range_to != "":
        return range_from + range_to
    else:
        return None

def is_historical():
    if toolkit.g.action == 'historical':
        return True


def get_formats(limit=100):
    try:
        # Get any additional formats added in the admin settings
        additional_formats = [x.strip() for x in toolkit.config.get('ckan.datavic.authorised_resource_formats', []).split(',')]
        q = toolkit.request.GET.get('q', '')
        list_of_formats = [x.encode('utf-8') for x in
                            toolkit.get_action('format_autocomplete')({}, {'q': q, 'limit': limit}) if x] + additional_formats
        list_of_formats = sorted(list(set(list_of_formats)))
        dict_of_formats = []
        for item in list_of_formats:
            if item == ' ' or item == '':
                continue
            else:
                dict_of_formats.append({'value': item.lower(), 'text': item.upper()})
        dict_of_formats.insert(0, {'value': '', 'text': 'Please select'})
    except Exception as e:
        log.error(e)
        return []
    else:
        return dict_of_formats


def _parse_date(date_str):
    try:
        return calendar.timegm(time.strptime(date_str, "%Y-%m-%d"))
    except Exception as e:
        log.error(e)
        return None


def dataset_fields(dataset_type='dataset'):
    schema = toolkit.h.scheming_get_dataset_schema(dataset_type)
    return schema.get('dataset_fields', [])

