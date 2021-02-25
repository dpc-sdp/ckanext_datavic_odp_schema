# def historical_resources_list(self, resource_list):
#     sorted_resource_list = {}
#     i = 0
#     for resource in resource_list:
#         i += 1
#         if resource.get('period_start') is not None and resource.get('period_start') != 'None' and resource.get(
#                 'period_start') != '':
#             key = parse_date(resource.get('period_start')[:10]) or 'zzz' + str(i)
#         else:
#             key = 'zzz' + str(i)
#         resource['key'] = key
#         # print parser.parse(resource.get('period_start')).strftime("%Y-%M-%d") + " " + resource.get('period_start')
#         sorted_resource_list[key] = resource

#     list = sorted(sorted_resource_list.values(), key=lambda item: str(item.get('key')), reverse=True)
#     # for item in list:
#     #    print item.get('period_start') + " " + str(item.get('key'))
#     return list


# def historical_resources_range(resource_list):
#     range_from = ""
#     from_ts = None
#     range_to = ""
#     to_ts = None
#     for resource in resource_list:

#         if resource.get('period_start') is not None and resource.get('period_start') != 'None' and resource.get(
#                 'period_start') != '':
#             ts = parse_date(resource.get('period_start')[:10])
#             if ts and (from_ts is None or ts < from_ts):
#                 from_ts = ts
#                 range_from = resource.get('period_start')[:10]
#         if resource.get('period_end') is not None and resource.get('period_end') != 'None' and resource.get(
#                 'period_end') != '':
#             ts = parse_date(resource.get('period_end')[:10])
#             if ts and (to_ts is None or ts > to_ts):
#                 to_ts = ts
#                 range_to = resource.get('period_end')[:10]

#     if range_from != "" and range_to != "":
#         return range_from + " to " + range_to
#     elif range_from != "" or range_to != "":
#         return range_from + range_to
#     else:
#         return None


# def is_historical(self):
#     if toolkit.c.action == 'historical':
#         return True

