import ckan.plugins as p

from ckanext.hierarchy import helpers as hierarchy_helpers


def datavic_group_tree(organizations=[], type_='organization'):
    full_tree_list = p.toolkit.get_action('group_tree')({}, {'type': type_})

    if not organizations:
        return full_tree_list
    else:
        filtered_tree_list = hierarchy_helpers.group_tree_filter(organizations, full_tree_list)

        revised_filtered_tree_list = []

        for i in range(len(filtered_tree_list)):
            org_name = filtered_tree_list[i]['name']
            # Loop through full_tree_list to see if org_name appears as a top-level list item
            for org in full_tree_list:
                if org['name'] == org_name:
                    revised_filtered_tree_list.append(filtered_tree_list[i])

        return revised_filtered_tree_list
