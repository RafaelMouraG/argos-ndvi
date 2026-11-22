"""Configuração do serviço: provedores STAC, classes SCL e opções do GDAL."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Provedor:
    """Catálogo STAC e nomes dos assets usados no cálculo."""

    nome: str
    url_stac: str
    colecao: str
    asset_red: str
    asset_nir: str
    asset_scl: str


PROVEDORES: dict[str, Provedor] = {
    # Collection 1 (processing baseline 05.xx). Os assets trazem raster:bands com
    # scale 0.0001 e offset -0.1, então a correção radiométrica vem do próprio item.
    "earth-search": Provedor(
        nome="earth-search",
        url_stac="https://earth-search.aws.element84.com/v1",
        colecao="sentinel-2-c1-l2a",
        asset_red="red",
        asset_nir="nir",
        asset_scl="scl",
    ),
}


def provedor_ativo() -> Provedor:
    nome = os.environ.get("ARGOS_PROVEDOR", "earth-search")
    try:
        return PROVEDORES[nome]
    except KeyError as exc:
        opcoes = ", ".join(PROVEDORES)
        raise RuntimeError(f"Provedor STAC desconhecido: {nome!r}. Opções: {opcoes}") from exc


# Scene Classification Layer (Sen2Cor)
SCL_CLASSES: dict[int, str] = {
    0: "sem_dado",
    1: "saturado_ou_defeituoso",
    2: "area_escura",
    3: "sombra_de_nuvem",
    4: "vegetacao",
    5: "nao_vegetado",
    6: "agua",
    7: "nao_classificado",
    8: "nuvem_media_probabilidade",
    9: "nuvem_alta_probabilidade",
    10: "cirrus",
    11: "neve",
}

# Pixels descartados antes do cálculo do NDVI
SCL_MASCARADAS: frozenset[int] = frozenset({0, 1, 3, 8, 9, 10})

# Leitura parcial de COG por HTTP: evita listar diretórios e agrupa range requests
GDAL_OPCOES: dict[str, str] = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "GDAL_HTTP_MULTIPLEX": "YES",
    "GDAL_HTTP_VERSION": "2",
    "GDAL_HTTP_MAX_RETRY": "3",
    "GDAL_HTTP_RETRY_DELAY": "1",
    "VSI_CACHE": "TRUE",
}

MAX_AREA_HA = float(os.environ.get("ARGOS_MAX_AREA_HA", "5000"))
MAX_WORKERS_SERIE = int(os.environ.get("ARGOS_MAX_WORKERS", "4"))
MAX_CENAS_SERIE = int(os.environ.get("ARGOS_MAX_CENAS_SERIE", "150"))
