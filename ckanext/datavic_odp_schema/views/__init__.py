from .odp_dataset import odp_dataset
from .sitemap import sitemap

def get_blueprints():
    return [odp_dataset, sitemap]
