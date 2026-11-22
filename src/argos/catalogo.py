"""Busca de cenas Sentinel-2 via STAC e leitura dos metadados radiométricos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time

import pystac
from pystac_client import Client
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from argos.config import Provedor, provedor_ativo

INICIO_BASELINE_04 = date(2022, 1, 25)


@dataclass(frozen=True)
class Cena:
    item: pystac.Item
    data: date
    tile: str
    nuvens_cena_pct: float | None

    @property
    def id(self) -> str:
        return self.item.id

    @property
    def satelite(self) -> str:
        return str(self.item.properties.get("platform", "sentinel-2"))

    def href(self, asset: str) -> str:
        try:
            return self.item.assets[asset].href
        except KeyError as exc:
            raise KeyError(f"Item {self.id} não tem o asset {asset!r}.") from exc


def escala_offset(item: pystac.Item, asset: str) -> tuple[float, float]:
    """Escala e offset para converter DN em reflectância.

    Ordem de preferência:
    1. raster:bands do asset (o Earth Search C1 publica scale 0.0001 e offset -0.1);
    2. s2:processing_baseline do item (>= 04.00 implica offset de -1000 DN);
    3. data da aquisição (a baseline 04.00 entrou em operação em 25/01/2022).
    """
    bandas = item.assets[asset].extra_fields.get("raster:bands") or []
    if bandas and ("scale" in bandas[0] or "offset" in bandas[0]):
        return float(bandas[0].get("scale", 1.0)), float(bandas[0].get("offset", 0.0))

    baseline = item.properties.get("s2:processing_baseline")
    try:
        com_offset = float(baseline) >= 4.0
    except (TypeError, ValueError):
        data = item.datetime.date() if item.datetime else None
        com_offset = data is None or data >= INICIO_BASELINE_04
    return 1e-4, (-0.1 if com_offset else 0.0)


def _tile(item: pystac.Item) -> str:
    p = item.properties
    if {"mgrs:utm_zone", "mgrs:latitude_band", "mgrs:grid_square"} <= p.keys():
        return f"{int(p['mgrs:utm_zone']):02d}{p['mgrs:latitude_band']}{p['mgrs:grid_square']}"
    return str(p.get("s2:mgrs_tile", item.id))


def _data(item: pystac.Item) -> date:
    if item.datetime is not None:
        return item.datetime.date()
    return datetime.fromisoformat(item.properties["start_datetime"]).date()


def selecionar_cenas(
    itens: list[pystac.Item], geom: BaseGeometry, max_nuvens_cena: float
) -> list[Cena]:
    """Filtra itens que contêm o talhão inteiro e mantém um por data e tile.

    Retorna da cena mais recente para a mais antiga.
    """
    melhores: dict[tuple[date, str], Cena] = {}
    for item in itens:
        nuvens = item.properties.get("eo:cloud_cover")
        if nuvens is not None and nuvens > max_nuvens_cena:
            continue
        if item.geometry is None or not shape(item.geometry).contains(geom):
            continue
        cena = Cena(item=item, data=_data(item), tile=_tile(item), nuvens_cena_pct=nuvens)
        chave = (cena.data, cena.tile)
        atual = melhores.get(chave)
        if atual is None or (nuvens or 0) < (atual.nuvens_cena_pct or 0):
            melhores[chave] = cena
    return sorted(melhores.values(), key=lambda c: (c.data, c.tile), reverse=True)


def buscar_cenas(
    geom: BaseGeometry,
    inicio: date,
    fim: date,
    max_nuvens_cena: float,
    provedor: Provedor | None = None,
    max_itens: int = 300,
) -> list[Cena]:
    provedor = provedor or provedor_ativo()
    cliente = Client.open(provedor.url_stac)
    busca = cliente.search(
        collections=[provedor.colecao],
        intersects=mapping(geom),
        datetime=[
            datetime.combine(inicio, time.min, tzinfo=UTC),
            datetime.combine(fim, time.max, tzinfo=UTC),
        ],
        query={"eo:cloud_cover": {"lte": max_nuvens_cena}},
        max_items=max_itens,
    )
    return selecionar_cenas(list(busca.items()), geom, max_nuvens_cena)
