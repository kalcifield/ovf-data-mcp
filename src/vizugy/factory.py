import os

from .providers import ArcGISProvider
from .service import VizugyService


def create_service() -> VizugyService:
    provider = ArcGISProvider(
        os.getenv("VIZUGY_ARCGIS_URL", "https://geoportal.vizugy.hu/arcgis/rest"),
        float(os.getenv("VIZUGY_TIMEOUT_SECONDS", "15")),
        float(os.getenv("VIZUGY_CACHE_TTL_SECONDS", "300")),
    )
    return VizugyService(provider)

