import os

from .providers import ArcGISProvider
from .service import VizugyService
from .vra_provider import VRAProvider


def create_service() -> VizugyService:
    provider = ArcGISProvider(
        os.getenv("VIZUGY_ARCGIS_URL", "https://geoportal.vizugy.hu/arcgis/rest"),
        float(os.getenv("VIZUGY_TIMEOUT_SECONDS", "15")),
        float(os.getenv("VIZUGY_CACHE_TTL_SECONDS", "300")),
    )
    vra = VRAProvider(
        os.getenv("VIZUGY_VRA_URL", "https://vmservice.vizugy.hu/vraquery"),
        os.getenv("VIZUGY_TOKEN_URL", "https://data.vizugy.hu/AuthApi/auth/token"),
        float(os.getenv("VIZUGY_TIMEOUT_SECONDS", "15")),
    )
    return VizugyService(provider, vra)
