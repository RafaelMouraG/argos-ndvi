import numpy as np
import pytest

from argos.ndvi import (
    CLASSE_INVALIDA,
    calcular_ndvi,
    classificar_absoluto,
    classificar_relativo,
    estatisticas,
    para_reflectancia,
    resumir_zonas,
    zonas_absolutas,
)


def test_reflectancia_aplica_offset_da_baseline_04():
    dn = np.array([1000, 1500, 5500], dtype=np.uint16)
    np.testing.assert_allclose(para_reflectancia(dn, 1e-4, -0.1), [0.0, 0.05, 0.45], atol=1e-6)


def test_reflectancia_negativa_truncada_em_zero():
    dn = np.array([1, 900], dtype=np.uint16)
    assert (para_reflectancia(dn, 1e-4, -0.1) == 0).all()


def test_offset_ignorado_distorce_ndvi():
    """Motivo da correção: sem o offset, um NDVI de 0,80 vira 0,57."""
    red_dn, nir_dn = np.array([1500.0]), np.array([5500.0])
    validos = np.array([True])
    certo = calcular_ndvi(
        para_reflectancia(red_dn, 1e-4, -0.1), para_reflectancia(nir_dn, 1e-4, -0.1), validos
    )
    errado = calcular_ndvi(red_dn * 1e-4, nir_dn * 1e-4, validos)
    assert certo[0] == pytest.approx(0.80, abs=1e-5)
    assert errado[0] == pytest.approx(0.5714, abs=1e-4)


def test_ndvi_marca_invalidos_e_soma_zero_como_nan():
    red = np.array([0.05, 0.0, 0.05], dtype=np.float32)
    nir = np.array([0.45, 0.0, 0.45], dtype=np.float32)
    ndvi = calcular_ndvi(red, nir, np.array([True, True, False]))
    assert ndvi[0] == pytest.approx(0.8)
    assert np.isnan(ndvi[1]) and np.isnan(ndvi[2])


def test_estatisticas_vazias_falham():
    with pytest.raises(ValueError):
        estatisticas(np.array([]))


def test_classificacao_absoluta_respeita_limites():
    ndvi = np.array([0.05, 0.10, 0.29, 0.30, 0.59, 0.60, 0.9, np.nan], dtype=np.float32)
    classes = classificar_absoluto(ndvi, (0.10, 0.30, 0.60))
    assert classes.tolist() == [0, 1, 1, 2, 2, 3, 3, CLASSE_INVALIDA]


def test_classificacao_relativa_usa_mediana():
    ndvi = np.array([0.50, 0.70, 0.90], dtype=np.float32)
    assert classificar_relativo(ndvi, 0.70, 0.15).tolist() == [0, 1, 2]


def test_resumo_de_zonas_em_hectares():
    classes = np.array([1, 1, 3, 3, 3, CLASSE_INVALIDA], dtype=np.int8)
    resumo = resumir_zonas(classes, zonas_absolutas((0.1, 0.3, 0.6)), area_pixel_ha=0.01)
    por_classe = {z["classe"]: z for z in resumo}
    assert por_classe["baixo_vigor"] == {
        "classe": "baixo_vigor", "faixa": "0.10 a 0.30", "area_ha": 0.02, "percentual": 40.0,
    }
    assert por_classe["alto_vigor"]["percentual"] == 60.0


def test_filtro_de_area_minima_preserva_invalidos():
    from argos.raster import filtrar_area_minima

    classes = np.full((10, 10), 2, dtype=np.int8)
    classes[2, 2] = 1  # mancha de 1 pixel
    classes[5:8, 5:8] = 1  # mancha de 9 pixels
    classes[0, :] = CLASSE_INVALIDA
    filtradas = filtrar_area_minima(classes, 4)
    assert filtradas[2, 2] == 2
    assert (filtradas[5:8, 5:8] == 1).all()
    assert (filtradas[0, :] == CLASSE_INVALIDA).all()
    assert filtradas.dtype == np.int8
    assert filtrar_area_minima(classes, 1) is classes
