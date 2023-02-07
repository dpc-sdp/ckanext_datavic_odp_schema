from __future__ import annotations

import re
from typing import Any, Optional

import ckan.plugins.toolkit as tk

from ckanapi import RemoteCKAN


def valid_url(url: str) -> bool:
    """Check if URL is valid (starts with http or https protocol)"""
    return bool(re.search(r"^(http|https)://", url))


def valid_api_key(api_key: str) -> bool:
    """Check if API key contains invalid characters"""
    return not bool(re.search(r"[^0-9a-f-]", api_key))


def get_remote_organisations(
    source_url: str, api_key
) -> Optional[list[dict[str, Any]]]:
    remote_ckan = RemoteCKAN(source_url, apikey=api_key)
    try:
        return remote_ckan.call_action(
            "organization_list",
            {
                "all_fields": True,
                "include_dataset_count": False,
                "include_groups": True,
            },
        )
    except Exception as e:
        return


def find_new_organisations(
    remote_orgs: list[dict[str, Any]], local_orgs: list[str]
) -> list[dict[str, Any]]:
    """Compare a list of remote orgs to a list of local orgs to find any
    new orgs on the remote CKAN instance"""
    return [org for org in remote_orgs if org["name"] not in local_orgs]


def create_new_organisations(
    new_orgs: list[dict[str, Any]]
) -> tuple[list[str], list[dict[str, Any]]]:
    """Creates any new organisations that do not exist in the local CKAN instance"""
    successes: list[str] = []
    errors: list[dict[str, Any]] = []

    for org in new_orgs:
        try:
            tk.get_action("organization_create")(
                {},
                {
                    "id": org["id"],
                    "name": org["name"],
                    "title": org["title"],
                },
            )
        except Exception as e:
            errors.append({"name": org["name"], "error": str(e)})
            continue

        successes.append(org["name"])

    return successes, errors


def reset_existing_hierarchy(
    context: dict[str, Any], org_list: list[str]
) -> tuple[list[str], list[dict[str, Any]]]:
    """Reset any existing hierarchy assignments for the local organisations"""
    successes: list[str] = []
    errors: list[dict[str, Any]] = []

    for org_name in org_list:
        try:
            organisation = tk.get_action("organization_show")(context, {"id": org_name})

            if not organisation["groups"]:
                continue

            tk.get_action("organization_patch")(
                context, {"id": organisation["id"], "groups": []}
            )
        except Exception as e:
            errors.append({"name": org_name, "error": str(e)})
            continue

        successes.append(org_name)

    return successes, errors


def assign_parent_organisations(context: dict[str, Any], remote_orgs):
    successes: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for remote_org in remote_orgs:
        if not remote_org["groups"]:
            continue

        try:
            tk.get_action("organization_patch")(
                context, {"id": remote_org["name"], "groups": remote_org["groups"]}
            )
        except Exception as e:
            errors.append({"name": remote_org["name"], "error": str(e)})
            continue

        successes.append({"name": remote_org["name"], "groups": remote_org["groups"]})
    return successes, errors


def output_header(heading: str) -> str:
    return f"""
    - - - - - - -
    >>> {heading}...
    - - - - - - -
    """


def output_successes(
    successes, action, heading="Organisations", label="Organisation name"
):
    output = ">>>> %s %s:\n" % (heading, action)
    for success in successes:
        output += "%s: %s\n" % (
            label,
            success["name"] if type(success) is dict else success,
        )
        if type(success) is dict:
            output += "Groups added: %s\n" % success["groups"]

    return output


def output_errors(errors, action, heading="Organisation", label="Organisation name"):
    output = ">>>> %s %s errors:\n" % (heading, action)
    for error in errors:
        output += "%s: %s\n" % (label, error["name"])
        output += "Error: %s\n" % error["error"]

    return output


def reconcile_local_organisations(context, source_url, api_key):
    """
    Main function for reconciling a local set of organisations against a remote set of organisations
    :param context:
    :param source_url:
    :param api_key:
    :return:
    """
    output = ""

    local_orgs: list[str] = tk.get_action("organization_list")(context, {})
    remote_orgs: Optional[list[dict[str, Any]]] = get_remote_organisations(
        source_url, api_key
    )

    if not remote_orgs:
        return output + "ERROR fetching remote organisations"

    new_orgs: list[dict[str, Any]] = find_new_organisations(remote_orgs, local_orgs)

    if new_orgs:
        output += output_header("New orgs to create")
        new_orgs_created, errors = create_new_organisations(new_orgs)

        if new_orgs_created:
            output += output_successes(new_orgs_created, "created", "New organisations")
        if errors:
            output += output_errors(errors, "create")
    else:
        output += "No new organisations to create.\n"

    output += output_header("Resetting existing organisation hierarchy")

    orgs_reset, errors = reset_existing_hierarchy(context, local_orgs)

    if orgs_reset:
        output += output_successes(orgs_reset, "reset")
    if errors:
        output += output_errors(errors, "reset")

    output += output_header("Assigning parents to local orgs")

    orgs_patched, errors = assign_parent_organisations(context, remote_orgs)

    if orgs_patched:
        output += output_successes(orgs_patched, "patched")
    if errors:
        output += output_errors(errors, "patch")

    return output + "\nCOMPLETED\n"
