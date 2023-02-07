from .odp_dataset import odp_dataset
from .organisation import organisation
from .sitemap import sitemap

def get_blueprints():
    return [odp_dataset, organisation, sitemap]
