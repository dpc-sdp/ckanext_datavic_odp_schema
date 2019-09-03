import re

from ckanapi import RemoteCKAN
from ckan.logic import get_action as _get_action


def valid_url(url):
    return re.search(r"^(http|https)://", url)


def contains_invalid_chars(value):
    return re.search(r"[^0-9a-f-]", value)


def get_remote_organisations(source_url, api_key):
    remote_ckan = RemoteCKAN(source_url, apikey=api_key)
    try:
        return remote_ckan.call_action('organization_list', {
            'all_fields': True,
            'include_dataset_count': False,
            'include_groups': True
        })
    except Exception, e:
        return str(e)


def find_new_organisations(remote_orgs, local_orgs):
    """
    Compare a list of remote orgs to a list of local orgs to find any new orgs on the remote CKAN instance
    :param remote_orgs: list of remote organisation dicts
    :param local_orgs: list of local organisation names
    :return:
    """
    new_organisations = []
    for remote_org in remote_orgs:
        if remote_org['name'] not in local_orgs:
            new_organisations.append(remote_org)

    return new_organisations


def create_new_organisations(new_organisations):
    """
    Creates any new organisations that do not exist in the local CKAN instance
    :param new_organisations: A list of dicts containing organisation details
    :return:
    """
    successes = []
    errors = []
    for new_org in new_organisations:
        try:
            _get_action('organization_create')({}, {
                'id': new_org['id'],
                'name': new_org['name'],
                'title': new_org['title'],
            })
            successes.append(new_org['name'])
        except Exception, e:
            errors.append({'name': new_org['name'], 'error': str(e)})
            continue

    return successes, errors


def reset_existing_hierarchy(context, organisations):
    """
    Resets any existing parent-child relationships for the provided list of organisation ids/names
    :param context:
    :param organisations: A list of organisation ids or names
    :return:
    """
    successes = []
    errors = []
    for org in organisations:
        try:
            organisation = _get_action('organization_show')(context, {'id': org})
            if organisation['groups']:
                _get_action('organization_patch')(context, {'id': organisation['id'], 'groups': []})
                successes.append(org)
        except Exception, e:
            errors.append({'name': org, 'error': str(e)})
            continue

    return successes, errors


def assign_parent_organisations(context, remote_orgs):
    successes = []
    errors = []
    for remote_org in remote_orgs:
        if remote_org['groups']:
            try:
                _get_action('organization_patch')(context, {'id': remote_org['name'], 'groups': remote_org['groups']})
                successes.append({'name': remote_org['name'], 'groups': remote_org['groups']})
            except Exception, e:
                errors.append({'name': remote_org['name'], 'error': str(e)})
                continue

    return successes, errors


def output_header(heading):
    output = '- - - - - - -\n'
    output += '>>> %s...\n' % heading
    output += '- - - - - - -\n'

    return output


def output_successes(successes, action, heading='Organisations', label='Organisation name'):
    output = '>>>> %s %s:\n' % (heading, action)
    for success in successes:
        output += '%s: %s\n' % (label, success['name'] if type(success) is dict else success)
        if type(success) is dict:
            output += 'Groups added: %s\n' % success['groups']

    return output


def output_errors(errors, action, heading='Organisation', label='Organisation name'):
    output = '>>>> %s %s errors:\n' % (heading, action)
    for error in errors:
        output += '%s: %s\n' % (label, error['name'])
        output += 'Error: %s\n' % error['error']

    return output


def reconcile_local_organisations(context, source_url, api_key):
    """
    Main function for reconciling a local set of organisations against a remote set of organisations
    :param context:
    :param source_url:
    :param api_key:
    :return:
    """
    output = ''

    # Get local organisations & org tree
    local_orgs = _get_action('organization_list')(context, {})

    remote_orgs = get_remote_organisations(source_url, api_key)

    if not type(remote_orgs) is list:
        return output + 'ERROR fetching remote organisations'

    # Find any new organisations on the remote CKAN instance that don't exist locally and create them
    new_orgs = find_new_organisations(remote_orgs, local_orgs)

    if len(new_orgs):
        output += output_header('New orgs to create')
        new_orgs_created, errors = create_new_organisations(new_orgs)
        if new_orgs_created:
            output += output_successes(new_orgs_created, 'created', 'New organisations')
        if errors:
            output += output_errors(errors, 'create')
    else:
        output += 'No new organisations to create.\n'

    output += output_header('Resetting existing organisation hierarchy')

    # Reset any existing hierarchy assignments for the local organisations
    orgs_reset, errors = reset_existing_hierarchy(context, local_orgs)

    if orgs_reset:
        output += output_successes(orgs_reset, 'reset')
    if errors:
        output += output_errors(errors, 'reset')

    output += output_header('Assigning parents to local orgs')

    # Assign parent orgs to local orgs where required
    orgs_patched, errors = assign_parent_organisations(context, remote_orgs)

    if orgs_patched:
        output += output_successes(orgs_patched, 'patched')
    if errors:
        output += output_errors(errors, 'patch')

    return output + '\nCOMPLETED\n'
