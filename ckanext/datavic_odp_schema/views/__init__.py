from .odp_dataset import odp_dataset
from .sitemap import sitemap
from .odp_api import odpapi

def get_blueprints():
    return [odp_dataset, sitemap, odpapi]
