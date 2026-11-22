"""Validação do talhão, reprojeção de vetores e cálculo de área."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import shapely
from pyproj import CRS, Transformer
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

WGS84 = CRS.from_epsg(4326)

Talhao = Polygon | MultiPolygon


class GeometriaInvalida(ValueError):
    """O GeoJSON recebido não descreve um talhão utilizável."""


def carregar_talhao(geojson: Mapping[str, Any]) -> Talhao:
    """Aceita Geometry, Feature ou FeatureCollection com um único talhão, em WGS84."""
    if not isinstance(geojson, Mapping):
        raise GeometriaInvalida("O GeoJSON deve ser um objeto.")

    tipo = geojson.get("type")
    if tipo == "FeatureCollection":
        features = geojson.get("features") or []
        if len(features) != 1:
            raise GeometriaInvalida("A FeatureCollection deve conter exatamente um talhão.")
        geojson = features[0]
        tipo = geojson.get("type")
    if tipo == "Feature":
        geojson = geojson.get("geometry") or {}
        tipo = geojson.get("type")
    if tipo not in ("Polygon", "MultiPolygon"):
        raise GeometriaInvalida(f"Tipo {tipo!r} não suportado. Use Polygon ou MultiPolygon.")

    try:
        geom = shape(geojson)
    except Exception as exc:  # shapely lança tipos variados para coordenadas malformadas
        raise GeometriaInvalida(f"GeoJSON malformado: {exc}") from exc

    if geom.is_empty:
        raise GeometriaInvalida("A geometria está vazia.")
    minx, miny, maxx, maxy = geom.bounds
    if not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
        raise GeometriaInvalida(
            "Coordenadas fora do intervalo de longitude e latitude. O GeoJSON deve estar "
            "em WGS84 (EPSG:4326), na ordem longitude, latitude."
        )
    if not geom.is_valid:
        raise GeometriaInvalida(f"Geometria inválida: {explain_validity(geom)}")
    return geom


def reprojetar(geom: BaseGeometry, origem: Any, destino: Any) -> BaseGeometry:
    transformador = Transformer.from_crs(
        CRS.from_user_input(origem), CRS.from_user_input(destino), always_xy=True
    )
    return shapely.transform(geom, transformador.transform, interleaved=False)


def crs_sirgas_utm(geom_wgs84: BaseGeometry) -> CRS:
    """SIRGAS 2000 / UTM do fuso do centroide; WGS84 / UTM fora da área do SIRGAS."""
    centro = geom_wgs84.centroid
    lon, lat = centro.x, centro.y
    zona = int((lon + 180) // 6) + 1
    hemisferio = "S" if lat < 0 else "N"
    alvo = f"UTM zone {zona}{hemisferio}"

    infos = query_utm_crs_info(
        datum_name="SIRGAS 2000", area_of_interest=AreaOfInterest(lon, lat, lon, lat)
    )
    for info in infos:
        if info.name.endswith(alvo):
            return CRS.from_authority(info.auth_name, info.code)
    return CRS.from_epsg((32700 if lat < 0 else 32600) + zona)


def area_ha(geom_wgs84: BaseGeometry) -> tuple[float, CRS]:
    """Área do talhão em hectares, medida em SIRGAS 2000 / UTM."""
    crs = crs_sirgas_utm(geom_wgs84)
    return reprojetar(geom_wgs84, WGS84, crs).area / 10_000, crs
