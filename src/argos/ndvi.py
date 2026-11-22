"""Álgebra de bandas, estatísticas zonais e zoneamento. Só numpy, sem I/O."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

CLASSE_INVALIDA = -1
LIMIARES_PADRAO: tuple[float, float, float] = (0.10, 0.30, 0.60)


@dataclass(frozen=True)
class Zona:
    codigo: int
    classe: str
    faixa: str


def para_reflectancia(dn: np.ndarray, escala: float, offset: float) -> np.ndarray:
    """Converte número digital em reflectância: rho = DN * escala + offset.

    Valores negativos (superfícies muito escuras após o offset) são truncados em 0,
    o que mantém o NDVI no intervalo [-1, 1].
    """
    rho = dn.astype(np.float32) * np.float32(escala) + np.float32(offset)
    return np.clip(rho, 0.0, None)


def calcular_ndvi(red: np.ndarray, nir: np.ndarray, validos: np.ndarray) -> np.ndarray:
    """NDVI = (NIR - RED) / (NIR + RED). Pixels inválidos ficam como NaN."""
    soma = nir + red
    ok = validos & (soma > 0)
    ndvi = np.full(red.shape, np.nan, dtype=np.float32)
    np.divide(nir - red, soma, out=ndvi, where=ok)
    return ndvi


def estatisticas(valores: np.ndarray) -> dict[str, float]:
    if valores.size == 0:
        raise ValueError("Nenhum pixel válido para calcular estatísticas.")
    v = valores.astype(np.float64)
    return {
        "media": round(float(v.mean()), 4),
        "mediana": round(float(np.median(v)), 4),
        "minimo": round(float(v.min()), 4),
        "maximo": round(float(v.max()), 4),
        "desvio_padrao": round(float(v.std()), 4),
        "p10": round(float(np.percentile(v, 10)), 4),
        "p90": round(float(np.percentile(v, 90)), 4),
    }


def _classificar(ndvi: np.ndarray, limites: tuple[float, ...]) -> np.ndarray:
    classes = np.full(ndvi.shape, CLASSE_INVALIDA, dtype=np.int8)
    ok = ~np.isnan(ndvi)
    # digitize: < l0 -> 0, [l0, l1) -> 1, ...
    classes[ok] = np.digitize(ndvi[ok], limites)
    return classes


def zonas_absolutas(limiares: tuple[float, float, float]) -> list[Zona]:
    a, b, c = limiares
    return [
        Zona(0, "solo_exposto_ou_palhada", f"abaixo de {a:.2f}"),
        Zona(1, "baixo_vigor", f"{a:.2f} a {b:.2f}"),
        Zona(2, "vigor_moderado", f"{b:.2f} a {c:.2f}"),
        Zona(3, "alto_vigor", f"acima de {c:.2f}"),
    ]


def classificar_absoluto(ndvi: np.ndarray, limiares: tuple[float, float, float]) -> np.ndarray:
    return _classificar(ndvi, limiares)


def limites_relativos(mediana: float, tolerancia: float) -> tuple[float, float]:
    return (1 - tolerancia) * mediana, (1 + tolerancia) * mediana


def zonas_relativas(mediana: float, tolerancia: float) -> list[Zona]:
    inf, sup = limites_relativos(mediana, tolerancia)
    return [
        Zona(0, "abaixo_da_mediana", f"abaixo de {inf:.2f}"),
        Zona(1, "proximo_da_mediana", f"{inf:.2f} a {sup:.2f}"),
        Zona(2, "acima_da_mediana", f"acima de {sup:.2f}"),
    ]


def classificar_relativo(ndvi: np.ndarray, mediana: float, tolerancia: float) -> np.ndarray:
    return _classificar(ndvi, limites_relativos(mediana, tolerancia))


def resumir_zonas(
    classes: np.ndarray, zonas: list[Zona], area_pixel_ha: float
) -> list[dict[str, object]]:
    n_validos = int((classes != CLASSE_INVALIDA).sum())
    resumo = []
    for zona in zonas:
        n = int((classes == zona.codigo).sum())
        resumo.append(
            {
                "classe": zona.classe,
                "faixa": zona.faixa,
                "area_ha": round(n * area_pixel_ha, 2),
                "percentual": round(100 * n / n_validos, 1) if n_validos else 0.0,
            }
        )
    return resumo
