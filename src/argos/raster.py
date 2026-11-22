"""Leitura parcial dos rasters na grade nativa da cena.

O talhão é reprojetado para o SRC da cena; o raster nunca é reprojetado. A janela é
alinhada à grade da SCL (20 m) para que cada pixel da SCL corresponda exatamente a
um bloco de 2 x 2 pixels das bandas de 10 m.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from affine import Affine
from rasterio.features import geometry_mask
from rasterio.io import DatasetReader
from rasterio.windows import Window
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry


class ForaDaCena(ValueError):
    """O talhão não cabe inteiro na cena."""


@dataclass(frozen=True)
class Grade:
    janela_bandas: Window
    janela_scl: Window
    fator_scl: int
    transform: Affine
    shape: tuple[int, int]

    @property
    def area_pixel_m2(self) -> float:
        return abs(self.transform.a * self.transform.e)


def _checar_norte_acima(transform: Affine) -> None:
    if transform.b != 0 or transform.d != 0 or transform.a <= 0 or transform.e >= 0:
        raise ValueError("Raster rotacionado ou sem norte para cima não é suportado.")


def calcular_grade(ds_banda: DatasetReader, ds_scl: DatasetReader, geom: BaseGeometry) -> Grade:
    """Janela que cobre o talhão (já no SRC da cena), alinhada às duas grades."""
    if ds_banda.crs != ds_scl.crs:
        raise ValueError("Bandas e SCL estão em SRC diferentes.")
    tb, ts = ds_banda.transform, ds_scl.transform
    _checar_norte_acima(tb)
    _checar_norte_acima(ts)

    res_b, res_s = tb.a, ts.a
    fator = round(res_s / res_b)
    if fator < 1 or not math.isclose(fator * res_b, res_s, abs_tol=1e-6):
        raise ValueError(f"Resolução da SCL ({res_s} m) não é múltiplo da banda ({res_b} m).")
    if not (math.isclose(tb.c, ts.c, abs_tol=1e-6) and math.isclose(tb.f, ts.f, abs_tol=1e-6)):
        raise ValueError("Bandas e SCL não compartilham a mesma origem de grade.")

    x0, y0 = ts.c, ts.f
    minx, miny, maxx, maxy = geom.bounds
    c0 = math.floor((minx - x0) / res_s)
    c1 = math.ceil((maxx - x0) / res_s)
    r0 = math.floor((y0 - maxy) / res_s)
    r1 = math.ceil((y0 - miny) / res_s)
    if c0 < 0 or r0 < 0 or c1 > ds_scl.width or r1 > ds_scl.height:
        raise ForaDaCena("O talhão ultrapassa os limites da cena.")
    if c1 * fator > ds_banda.width or r1 * fator > ds_banda.height:
        raise ForaDaCena("O talhão ultrapassa os limites da banda.")

    largura, altura = c1 - c0, r1 - r0
    return Grade(
        janela_bandas=Window(c0 * fator, r0 * fator, largura * fator, altura * fator),
        janela_scl=Window(c0, r0, largura, altura),
        fator_scl=fator,
        transform=Affine(res_b, 0.0, x0 + c0 * res_s, 0.0, -res_b, y0 - r0 * res_s),
        shape=(altura * fator, largura * fator),
    )


def mascara_talhao(geom: BaseGeometry, grade: Grade) -> np.ndarray:
    """True para pixels cujo centro está dentro do talhão."""
    return geometry_mask(
        [mapping(geom)],
        out_shape=grade.shape,
        transform=grade.transform,
        invert=True,
        all_touched=False,
    )


def ler_scl(ds_scl: DatasetReader, grade: Grade) -> np.ndarray:
    scl = ds_scl.read(1, window=grade.janela_scl)
    if grade.fator_scl > 1:
        # Vizinho mais próximo exato: cada pixel de 20 m vira um bloco 2 x 2
        scl = np.repeat(np.repeat(scl, grade.fator_scl, axis=0), grade.fator_scl, axis=1)
    return scl


def ler_banda(ds: DatasetReader, grade: Grade) -> np.ndarray:
    dados = ds.read(1, window=grade.janela_bandas)
    if dados.shape != grade.shape:
        raise ValueError(f"Janela lida com forma {dados.shape}, esperada {grade.shape}.")
    return dados
