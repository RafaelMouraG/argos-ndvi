"""Orquestração do pipeline: busca, máscara, NDVI, zoneamento e relatório."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import numpy as np
import rasterio
from shapely.geometry.base import BaseGeometry

from argos import catalogo
from argos.catalogo import Cena, escala_offset
from argos.config import (
    GDAL_OPCOES,
    MAX_AREA_HA,
    MAX_CENAS_SERIE,
    MAX_WORKERS_SERIE,
    SCL_MASCARADAS,
    Provedor,
    provedor_ativo,
)
from argos.geometria import WGS84, GeometriaInvalida, area_ha, reprojetar
from argos.ndvi import (
    Zona,
    calcular_ndvi,
    classificar_absoluto,
    classificar_relativo,
    estatisticas,
    para_reflectancia,
    resumir_zonas,
    zonas_absolutas,
    zonas_relativas,
)
from argos.raster import Grade, calcular_grade, ler_banda, ler_scl, mascara_talhao

ModoZoneamento = Literal["absoluto", "relativo"]

LIMIAR_SATURACAO = 0.80
LIMIAR_EFEITO_BORDA_PCT = 5.0


class SemImagemDisponivel(LookupError):
    """Nenhuma cena utilizável no período pedido."""


@dataclass
class ResultadoCena:
    cena: Cena
    pct_mascarado_talhao: float
    aceita: bool
    ndvi: np.ndarray | None = None
    validos: np.ndarray | None = None
    dentro: np.ndarray | None = None
    grade: Grade | None = None
    crs_wkt: str | None = None
    correcao: dict[str, dict[str, float]] | None = None

    @property
    def area_pixel_ha(self) -> float:
        assert self.grade is not None
        return self.grade.area_pixel_m2 / 10_000

    def valores_validos(self) -> np.ndarray:
        assert self.ndvi is not None and self.validos is not None
        return self.ndvi[self.validos]


@dataclass
class Zoneamento:
    modo: ModoZoneamento
    classes: np.ndarray
    zonas: list[Zona]
    codigo_baixo: int


def validar_area(geom: BaseGeometry) -> tuple[float, Any]:
    area, crs = area_ha(geom)
    if area > MAX_AREA_HA:
        raise GeometriaInvalida(
            f"Talhão com {area:.0f} ha excede o limite de {MAX_AREA_HA:.0f} ha por requisição."
        )
    return area, crs


def processar_cena(
    cena: Cena, geom: BaseGeometry, provedor: Provedor, max_mascarado_pct: float
) -> ResultadoCena:
    """Lê a SCL primeiro e só busca RED e NIR se o talhão estiver limpo o bastante."""
    with rasterio.Env(**GDAL_OPCOES):
        with (
            rasterio.open(cena.href(provedor.asset_scl)) as ds_scl,
            rasterio.open(cena.href(provedor.asset_red)) as ds_red,
        ):
            crs_wkt = ds_red.crs.to_wkt()
            transform_red = ds_red.transform
            geom_cena = reprojetar(geom, WGS84, crs_wkt)
            grade = calcular_grade(ds_red, ds_scl, geom_cena)
            dentro = mascara_talhao(geom_cena, grade)
            n_dentro = int(dentro.sum())
            if n_dentro == 0:
                raise GeometriaInvalida("Talhão menor que um pixel de 10 m.")

            mascarado = np.isin(ler_scl(ds_scl, grade), list(SCL_MASCARADAS))
            pct = round(100 * int((mascarado & dentro).sum()) / n_dentro, 2)
            if pct > max_mascarado_pct:
                return ResultadoCena(cena=cena, pct_mascarado_talhao=pct, aceita=False)

            dn_red = ler_banda(ds_red, grade)
            nodata_red = ds_red.nodata if ds_red.nodata is not None else 0

        with rasterio.open(cena.href(provedor.asset_nir)) as ds_nir:
            if ds_nir.transform != transform_red or ds_nir.crs.to_wkt() != crs_wkt:
                raise ValueError("RED e NIR não estão na mesma grade.")
            dn_nir = ler_banda(ds_nir, grade)
            nodata_nir = ds_nir.nodata if ds_nir.nodata is not None else 0

    esc_red, off_red = escala_offset(cena.item, provedor.asset_red)
    esc_nir, off_nir = escala_offset(cena.item, provedor.asset_nir)
    red = para_reflectancia(dn_red, esc_red, off_red)
    nir = para_reflectancia(dn_nir, esc_nir, off_nir)

    validos = dentro & ~mascarado & (dn_red != nodata_red) & (dn_nir != nodata_nir)
    ndvi = calcular_ndvi(red, nir, validos)
    validos &= ~np.isnan(ndvi)

    return ResultadoCena(
        cena=cena,
        pct_mascarado_talhao=pct,
        aceita=True,
        ndvi=ndvi,
        validos=validos,
        dentro=dentro,
        grade=grade,
        crs_wkt=crs_wkt,
        correcao={
            "red": {"escala": esc_red, "offset": off_red},
            "nir": {"escala": esc_nir, "offset": off_nir},
        },
    )


def zonear(
    resultado: ResultadoCena,
    modo: ModoZoneamento,
    limiares: tuple[float, float, float],
    tolerancia: float,
    mediana: float,
) -> Zoneamento:
    assert resultado.ndvi is not None and resultado.validos is not None
    ndvi = np.where(resultado.validos, resultado.ndvi, np.nan)
    if modo == "absoluto":
        return Zoneamento(modo, classificar_absoluto(ndvi, limiares), zonas_absolutas(limiares), 1)
    return Zoneamento(
        modo,
        classificar_relativo(ndvi, mediana, tolerancia),
        zonas_relativas(mediana, tolerancia),
        0,
    )


def _avisos(
    stats: dict[str, float], pct_mascarado: float, area_vetorial: float, area_pixels: float
) -> list[str]:
    avisos = []
    if pct_mascarado > 0:
        avisos.append(
            f"{pct_mascarado:.1f}% do talhão foi mascarado pela SCL (nuvem, sombra, cirrus "
            "ou defeito) e não entrou nas estatísticas."
        )
    if stats["media"] > LIMIAR_SATURACAO:
        avisos.append(
            "NDVI médio acima de 0,80: o índice tende a saturar com dossel fechado e pode "
            "subestimar diferenças de vigor. Considere um índice de red-edge (NDRE)."
        )
    if area_vetorial > 0:
        diferenca = 100 * abs(area_pixels - area_vetorial) / area_vetorial
        if diferenca > LIMIAR_EFEITO_BORDA_PCT:
            avisos.append(
                f"A área em pixels difere {diferenca:.1f}% da área vetorial (efeito de borda). "
                "Talhões pequenos ou estreitos são os mais afetados."
            )
    return avisos


def montar_relatorio(
    resultado: ResultadoCena,
    zoneamento: Zoneamento,
    stats: dict[str, float],
    area_vetorial: float,
    crs_area: Any,
    talhao_id: str | None,
    limiar_alerta_pct: float,
) -> dict[str, Any]:
    assert resultado.dentro is not None and resultado.validos is not None
    px_ha = resultado.area_pixel_ha
    n_dentro = int(resultado.dentro.sum())
    n_validos = int(resultado.validos.sum())
    zonas = resumir_zonas(zoneamento.classes, zoneamento.zonas, px_ha)

    baixo = next(z for z, zona in zip(zonas, zoneamento.zonas, strict=True)
                 if zona.codigo == zoneamento.codigo_baixo)
    alerta = None
    if baixo["percentual"] >= limiar_alerta_pct:
        alerta = (
            f"{baixo['percentual']:.1f}% da área válida ({baixo['area_ha']:.2f} ha) está na "
            f"classe {baixo['classe']}; recomenda-se vistoria em campo."
        )

    cena = resultado.cena
    return {
        "talhao_id": talhao_id,
        "data_imagem": cena.data.isoformat(),
        "item_id": cena.id,
        "tile": cena.tile,
        "satelite": cena.satelite,
        "cobertura_nuvens_cena_pct": cena.nuvens_cena_pct,
        "pct_mascarado_talhao": resultado.pct_mascarado_talhao,
        "area_total_ha": round(area_vetorial, 2),
        "src_area": crs_area.to_string(),
        "area_valida_ha": round(n_validos * px_ha, 2),
        "area_mascarada_ha": round((n_dentro - n_validos) * px_ha, 2),
        "correcao_radiometrica": resultado.correcao,
        "estatisticas_ndvi": stats,
        "zoneamento": {"modo": zoneamento.modo, "zonas": zonas},
        "alerta": alerta,
        "avisos": _avisos(stats, resultado.pct_mascarado_talhao, area_vetorial, n_dentro * px_ha),
        "atribuicao": f"Contém dados modificados do Copernicus Sentinel {cena.data.year}",
    }


def analisar(
    geom: BaseGeometry,
    inicio: date,
    fim: date,
    *,
    max_nuvens_cena: float = 60.0,
    max_mascarado_pct: float = 10.0,
    modo: ModoZoneamento = "absoluto",
    limiares: tuple[float, float, float] = (0.10, 0.30, 0.60),
    tolerancia: float = 0.15,
    limiar_alerta_pct: float = 10.0,
    talhao_id: str | None = None,
    provedor: Provedor | None = None,
) -> tuple[dict[str, Any], ResultadoCena, Zoneamento]:
    """Analisa a cena mais recente em que o talhão está suficientemente limpo."""
    provedor = provedor or provedor_ativo()
    area_vetorial, crs_area = validar_area(geom)
    cenas = catalogo.buscar_cenas(geom, inicio, fim, max_nuvens_cena, provedor)
    if not cenas:
        raise SemImagemDisponivel(
            "Nenhuma cena contém o talhão inteiro no período com nuvens abaixo do limite."
        )

    for cena in cenas:
        resultado = processar_cena(cena, geom, provedor, max_mascarado_pct)
        if not resultado.aceita:
            continue
        valores = resultado.valores_validos()
        if valores.size == 0:
            continue
        stats = estatisticas(valores)
        zoneamento = zonear(resultado, modo, limiares, tolerancia, stats["mediana"])
        relatorio = montar_relatorio(
            resultado, zoneamento, stats, area_vetorial, crs_area, talhao_id, limiar_alerta_pct
        )
        return relatorio, resultado, zoneamento

    raise SemImagemDisponivel(
        f"{len(cenas)} cena(s) encontrada(s), todas com mais de {max_mascarado_pct:.0f}% "
        "do talhão mascarado."
    )


def serie_temporal(
    geom: BaseGeometry,
    inicio: date,
    fim: date,
    *,
    max_nuvens_cena: float = 80.0,
    max_mascarado_pct: float = 20.0,
    talhao_id: str | None = None,
    provedor: Provedor | None = None,
) -> dict[str, Any]:
    provedor = provedor or provedor_ativo()
    area_vetorial, crs_area = validar_area(geom)
    cenas = catalogo.buscar_cenas(geom, inicio, fim, max_nuvens_cena, provedor)
    if len(cenas) > MAX_CENAS_SERIE:
        raise SemImagemDisponivel(
            f"{len(cenas)} cenas no período; o limite é {MAX_CENAS_SERIE}. Reduza o intervalo."
        )

    def _processar(cena: Cena) -> ResultadoCena:
        return processar_cena(cena, geom, provedor, max_mascarado_pct)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS_SERIE) as executor:
        resultados = list(executor.map(_processar, sorted(cenas, key=lambda c: c.data)))

    pontos, descartadas = [], []
    for r in resultados:
        valores = r.valores_validos() if r.aceita else np.empty(0)
        if valores.size == 0:
            descartadas.append(
                {"data": r.cena.data.isoformat(), "item_id": r.cena.id,
                 "pct_mascarado_talhao": r.pct_mascarado_talhao}
            )
            continue
        assert r.dentro is not None
        stats = estatisticas(valores)
        pontos.append(
            {
                "data": r.cena.data.isoformat(),
                "item_id": r.cena.id,
                "satelite": r.cena.satelite,
                "media": stats["media"],
                "mediana": stats["mediana"],
                "desvio_padrao": stats["desvio_padrao"],
                "pct_mascarado_talhao": r.pct_mascarado_talhao,
                "pct_valido": round(100 * valores.size / int(r.dentro.sum()), 1),
            }
        )

    anos = sorted({p["data"][:4] for p in pontos})
    return {
        "talhao_id": talhao_id,
        "area_total_ha": round(area_vetorial, 2),
        "src_area": crs_area.to_string(),
        "periodo": {"inicio": inicio.isoformat(), "fim": fim.isoformat()},
        "pontos": pontos,
        "descartadas": descartadas,
        "atribuicao": (
            f"Contém dados modificados do Copernicus Sentinel {', '.join(anos)}" if anos else None
        ),
    }
