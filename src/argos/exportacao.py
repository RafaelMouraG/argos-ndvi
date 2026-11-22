"""Exportação dos resultados para abrir no QGIS: NDVI em GeoTIFF e zonas em GeoJSON."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import shapes
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from argos.analise import ResultadoCena, Zoneamento
from argos.geometria import WGS84, reprojetar


def _atribuicao(resultado: ResultadoCena) -> str:
    return f"Contém dados modificados do Copernicus Sentinel {resultado.cena.data.year}"


def salvar_ndvi(resultado: ResultadoCena, caminho: Path) -> Path:
    """GeoTIFF float32 no SRC da cena; fora do talhão e pixels mascarados = NaN."""
    assert resultado.ndvi is not None and resultado.validos is not None
    assert resultado.grade is not None
    ndvi = np.where(resultado.validos, resultado.ndvi, np.nan).astype(np.float32)
    altura, largura = ndvi.shape
    with rasterio.open(
        caminho,
        "w",
        driver="GTiff",
        height=altura,
        width=largura,
        count=1,
        dtype="float32",
        crs=resultado.crs_wkt,
        transform=resultado.grade.transform,
        nodata=np.nan,
        compress="deflate",
    ) as dst:
        dst.write(ndvi, 1)
        dst.set_band_description(1, "NDVI")
        dst.update_tags(
            DATA_IMAGEM=resultado.cena.data.isoformat(),
            ITEM_STAC=resultado.cena.id,
            ATRIBUICAO=_atribuicao(resultado),
        )
    return caminho


def salvar_zonas(resultado: ResultadoCena, zoneamento: Zoneamento, caminho: Path) -> Path:
    """Uma feição (Multi)Polygon por classe, em WGS84, com área medida no SRC da cena."""
    assert resultado.grade is not None and resultado.crs_wkt is not None
    classes = zoneamento.classes.astype(np.int16)
    poligonos: dict[int, list] = {}
    for geom, valor in shapes(classes, mask=classes >= 0, transform=resultado.grade.transform):
        poligonos.setdefault(int(valor), []).append(shape(geom))

    features = []
    for zona in zoneamento.zonas:
        partes = poligonos.get(zona.codigo)
        if not partes:
            continue
        uniao = unary_union(partes)
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(reprojetar(uniao, resultado.crs_wkt, WGS84)),
                "properties": {
                    "codigo": zona.codigo,
                    "classe": zona.classe,
                    "faixa": zona.faixa,
                    "area_ha": round(uniao.area / 10_000, 4),
                },
            }
        )

    colecao = {
        "type": "FeatureCollection",
        "name": f"zonas_{resultado.cena.data.isoformat()}",
        "features": features,
        "atribuicao": _atribuicao(resultado),
    }
    caminho.write_text(json.dumps(colecao, ensure_ascii=False), encoding="utf-8")
    return caminho
