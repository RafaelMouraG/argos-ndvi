from datetime import date

import numpy as np
import pytest
import rasterio

from argos import analise
from argos.cli import main
from argos.config import PROVEDORES
from argos.exportacao import salvar_ndvi, salvar_zonas

INICIO, FIM = date(2026, 11, 1), date(2026, 11, 20)
NDVI_ALTO = 0.8
NDVI_BAIXO = 0.08 / 0.28


def test_pipeline_completo(fabrica_cena, catalogo_falso, talhao_wgs84):
    catalogo_falso([fabrica_cena().item])
    relatorio, resultado, _ = analise.analisar(talhao_wgs84, INICIO, FIM, talhao_id="t-01")

    assert relatorio["data_imagem"] == "2026-11-10"
    assert relatorio["area_total_ha"] == pytest.approx(64.0, abs=0.01)
    assert relatorio["src_area"] == "EPSG:31983"
    # 100 de 6400 pixels sob nuvem
    assert relatorio["pct_mascarado_talhao"] == 1.56
    assert relatorio["area_valida_ha"] == 63.0
    assert relatorio["area_mascarada_ha"] == 1.0
    assert relatorio["correcao_radiometrica"]["nir"] == {"escala": 0.0001, "offset": -0.1}

    media = (1600 * NDVI_BAIXO + 4700 * NDVI_ALTO) / 6300
    stats = relatorio["estatisticas_ndvi"]
    assert stats["media"] == pytest.approx(media, abs=1e-3)
    assert stats["mediana"] == pytest.approx(NDVI_ALTO, abs=1e-4)
    assert stats["minimo"] == pytest.approx(NDVI_BAIXO, abs=1e-4)

    zonas = {z["classe"]: z for z in relatorio["zoneamento"]["zonas"]}
    assert zonas["baixo_vigor"]["area_ha"] == 16.0
    assert zonas["baixo_vigor"]["percentual"] == 25.4
    assert zonas["alto_vigor"]["area_ha"] == 47.0
    assert zonas["vigor_moderado"]["area_ha"] == 0.0
    assert "25.4%" in relatorio["alerta"]
    assert relatorio["atribuicao"].endswith("Sentinel 2026")

    # A nuvem caiu exatamente nos pixels de 10 m correspondentes ao bloco de 20 m
    assert resultado.grade.fator_scl == 2
    assert not resultado.validos[_dentro_da_grade(resultado, 80, 120)]


def test_pula_cena_nublada_e_usa_a_anterior(fabrica_cena, catalogo_falso, talhao_wgs84):
    nublada = fabrica_cena("nublada", dia=15, nuvem_total=True).item
    nublada.properties["eo:cloud_cover"] = 20.0  # cena "limpa" no geral, talhão coberto
    limpa = fabrica_cena("limpa", dia=10).item
    catalogo_falso([nublada, limpa])

    relatorio, _, _ = analise.analisar(talhao_wgs84, INICIO, FIM)
    assert relatorio["item_id"] == "limpa"


def test_sem_cena_utilizavel(fabrica_cena, catalogo_falso, talhao_wgs84):
    nublada = fabrica_cena("nublada", nuvem_total=True).item
    nublada.properties["eo:cloud_cover"] = 20.0
    catalogo_falso([nublada])
    with pytest.raises(analise.SemImagemDisponivel, match="mascarado"):
        analise.analisar(talhao_wgs84, INICIO, FIM)


def test_zoneamento_relativo(fabrica_cena, catalogo_falso, talhao_wgs84):
    catalogo_falso([fabrica_cena().item])
    relatorio, _, _ = analise.analisar(talhao_wgs84, INICIO, FIM, modo="relativo")
    zonas = {z["classe"]: z for z in relatorio["zoneamento"]["zonas"]}
    assert zonas["abaixo_da_mediana"]["area_ha"] == 16.0
    assert zonas["proximo_da_mediana"]["area_ha"] == 47.0


def test_serie_temporal(fabrica_cena, catalogo_falso, talhao_wgs84):
    catalogo_falso([
        fabrica_cena("a", dia=5).item,
        fabrica_cena("b", dia=10).item,
        fabrica_cena("c", dia=15, nuvem_total=True).item,
    ])
    serie = analise.serie_temporal(talhao_wgs84, INICIO, FIM, max_nuvens_cena=100)
    assert [p["data"] for p in serie["pontos"]] == ["2026-11-05", "2026-11-10"]
    assert serie["descartadas"][0]["item_id"] == "c"
    assert serie["pontos"][0]["pct_valido"] == pytest.approx(98.4, abs=0.1)


def test_exportacao_para_qgis(fabrica_cena, catalogo_falso, talhao_wgs84, tmp_path):
    catalogo_falso([fabrica_cena().item])
    _, resultado, zoneamento = analise.analisar(talhao_wgs84, INICIO, FIM)

    tif = salvar_ndvi(resultado, tmp_path / "ndvi.tif")
    with rasterio.open(tif) as ds:
        assert ds.crs.to_epsg() == 32723
        dados = ds.read(1)
        assert np.count_nonzero(~np.isnan(dados)) == 6300
        assert "Copernicus" in ds.tags()["ATRIBUICAO"]

    import json

    zonas = json.loads(salvar_zonas(resultado, zoneamento, tmp_path / "z.geojson").read_text())
    areas = {f["properties"]["classe"]: f["properties"]["area_ha"] for f in zonas["features"]}
    assert areas == {"baixo_vigor": pytest.approx(16.0), "alto_vigor": pytest.approx(47.0)}


def test_cli_exportar(fabrica_cena, catalogo_falso, talhao_wgs84, tmp_path, capsys):
    import json

    from shapely.geometry import mapping

    catalogo_falso([fabrica_cena().item])
    entrada = tmp_path / "talhao.geojson"
    entrada.write_text(json.dumps(mapping(talhao_wgs84)))
    saida = tmp_path / "saida"
    codigo = main(["exportar", str(entrada), "--inicio", "2026-11-01", "--fim", "2026-11-20",
                   "--saida", str(saida)])
    assert codigo == 0
    assert sorted(p.name for p in saida.iterdir()) == [
        "ndvi_2026-11-10.tif", "relatorio_2026-11-10.json", "zonas_2026-11-10.geojson",
    ]


def test_provedor_padrao_usa_collection_1():
    assert PROVEDORES["earth-search"].colecao == "sentinel-2-c1-l2a"


def _dentro_da_grade(resultado, linha_cena: int, coluna_cena: int):
    """Converte linha e coluna da cena (10 m) para índices da janela recortada."""
    janela = resultado.grade.janela_bandas
    return int(linha_cena - janela.row_off), int(coluna_cena - janela.col_off)


def test_talhao_todo_baixo_vira_aviso_de_estadio(fabrica_cena, catalogo_falso, talhao_wgs84):
    """Talhão inteiro com NDVI baixo (ex.: emergência) não deve mandar vistoriar tudo."""
    catalogo_falso([fabrica_cena(todo_baixo=True).item])
    relatorio, _, _ = analise.analisar(talhao_wgs84, INICIO, FIM)
    zonas = {z["classe"]: z for z in relatorio["zoneamento"]["zonas"]}
    assert zonas["baixo_vigor"]["percentual"] == 100.0
    assert relatorio["alerta"] is None
    assert any("estádio inicial" in aviso for aviso in relatorio["avisos"])


def test_area_minima_absorve_manchas(fabrica_cena, catalogo_falso, talhao_wgs84):
    # A faixa de baixo vigor tem 16 ha: resiste a 10 ha e é absorvida com 20 ha
    catalogo_falso([fabrica_cena().item])
    for area_minima, esperado in ((10.0, 16.0), (20.0, 0.0)):
        relatorio, _, zoneamento = analise.analisar(
            talhao_wgs84, INICIO, FIM, area_minima_ha=area_minima
        )
        zonas = {z["classe"]: z for z in relatorio["zoneamento"]["zonas"]}
        assert zonas["baixo_vigor"]["area_ha"] == esperado
        assert relatorio["zoneamento"]["area_minima_ha"] == area_minima
        assert int((zoneamento.classes >= 0).sum()) == 6300  # válidos preservados
