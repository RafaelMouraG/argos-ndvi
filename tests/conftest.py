"""Cena Sentinel-2 sintética em disco para testar o pipeline sem rede.

Tile de 2 x 2 km em WGS84 / UTM 23S (oeste baiano), bandas de 10 m e SCL de 20 m.
Talhão quadrado de 800 x 800 m = 80 x 80 pixels = 64 ha.

Valores (com scale 0.0001 e offset -0.1):
- fundo: RED DN 1500 (0,05) e NIR DN 5500 (0,45) -> NDVI 0,80
- faixa de baixo vigor (20 colunas x 80 linhas = 16 ha): RED 2000 (0,10), NIR 2800 (0,18)
  -> NDVI 0,2857
- nuvem (SCL 9): bloco de 10 x 10 pixels de 10 m = 1 ha dentro do talhão
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pystac
import pytest
import rasterio
from affine import Affine
from shapely.geometry import box, mapping

from argos import catalogo
from argos.geometria import WGS84, reprojetar

CRS_CENA = "EPSG:32723"
X0, Y0 = 399_960.0, 8_700_040.0
N10 = 200  # pixels de 10 m por lado

TALHAO_UTM = box(400_500, 8_698_500, 401_300, 8_699_300)
COL_TALHAO, LIN_TALHAO = 54, 74  # primeiro pixel cujo centro está dentro do talhão
LADO_TALHAO = 80

COLS_BAIXO = slice(COL_TALHAO, COL_TALHAO + 20)
NUVEM_SCL = (slice(40, 45), slice(60, 65))  # em pixels de 20 m

RASTER_BANDS = [{"nodata": 0, "data_type": "uint16", "scale": 0.0001, "offset": -0.1}]


@dataclass
class CenaSintetica:
    item: pystac.Item
    pasta: Path


def _gravar(caminho: Path, dados: np.ndarray, resolucao: float) -> None:
    with rasterio.open(
        caminho,
        "w",
        driver="GTiff",
        height=dados.shape[0],
        width=dados.shape[1],
        count=1,
        dtype=dados.dtype,
        crs=CRS_CENA,
        transform=Affine(resolucao, 0, X0, 0, -resolucao, Y0),
        nodata=0,
    ) as dst:
        dst.write(dados, 1)


def criar_cena(
    pasta: Path,
    item_id: str,
    data: datetime,
    *,
    nuvem_total: bool = False,
    todo_baixo: bool = False,
    raster_bands: bool = True,
    baseline: str = "05.11",
) -> CenaSintetica:
    pasta.mkdir(parents=True, exist_ok=True)
    red = np.full((N10, N10), 1500, dtype=np.uint16)
    nir = np.full((N10, N10), 5500, dtype=np.uint16)
    linhas = slice(LIN_TALHAO, LIN_TALHAO + LADO_TALHAO)
    colunas_baixo = slice(None) if todo_baixo else COLS_BAIXO
    red[linhas, colunas_baixo] = 2000
    nir[linhas, colunas_baixo] = 2800

    scl = np.full((N10 // 2, N10 // 2), 4, dtype=np.uint8)
    if nuvem_total:
        scl[:] = 9
    else:
        scl[NUVEM_SCL] = 9

    _gravar(pasta / "red.tif", red, 10)
    _gravar(pasta / "nir.tif", nir, 10)
    _gravar(pasta / "scl.tif", scl, 20)

    tile = box(X0, Y0 - N10 * 10, X0 + N10 * 10, Y0)
    pegada = reprojetar(tile, CRS_CENA, WGS84)
    item = pystac.Item(
        id=item_id,
        geometry=mapping(pegada),
        bbox=list(pegada.bounds),
        datetime=data,
        properties={
            "platform": "sentinel-2c",
            "eo:cloud_cover": 100.0 if nuvem_total else 1.0,
            "s2:processing_baseline": baseline,
            "mgrs:utm_zone": 23,
            "mgrs:latitude_band": "L",
            "mgrs:grid_square": "MD",
        },
    )
    extras = {"raster:bands": RASTER_BANDS} if raster_bands else {}
    for chave in ("red", "nir"):
        item.add_asset(chave, pystac.Asset(str(pasta / f"{chave}.tif"), extra_fields=dict(extras)))
    item.add_asset("scl", pystac.Asset(str(pasta / "scl.tif")))
    return CenaSintetica(item=item, pasta=pasta)


@pytest.fixture
def talhao_wgs84():
    return reprojetar(TALHAO_UTM, CRS_CENA, WGS84)


@pytest.fixture
def fabrica_cena(tmp_path: Path) -> Callable[..., CenaSintetica]:
    def _criar(item_id: str = "S2C_23LMD_20261110", dia: int = 10, **kwargs) -> CenaSintetica:
        data = datetime(2026, 11, dia, 13, 10, tzinfo=UTC)
        return criar_cena(tmp_path / item_id, item_id, data, **kwargs)

    return _criar


@pytest.fixture
def catalogo_falso(monkeypatch):
    """Substitui a busca STAC por uma lista fixa de itens."""

    def _instalar(itens: list[pystac.Item]) -> None:
        def _buscar(geom, inicio, fim, max_nuvens_cena, provedor=None, max_itens=300):
            return catalogo.selecionar_cenas(itens, geom, max_nuvens_cena)

        monkeypatch.setattr(catalogo, "buscar_cenas", _buscar)

    return _instalar
