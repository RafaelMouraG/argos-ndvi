from datetime import UTC, datetime

import pytest

from argos.catalogo import escala_offset, selecionar_cenas


def test_escala_offset_vem_do_raster_bands(fabrica_cena):
    item = fabrica_cena().item
    assert escala_offset(item, "red") == (0.0001, -0.1)


@pytest.mark.parametrize("baseline, offset", [("05.11", -0.1), ("04.00", -0.1), ("03.01", 0.0)])
def test_escala_offset_pela_baseline(fabrica_cena, baseline, offset):
    item = fabrica_cena(raster_bands=False, baseline=baseline).item
    assert escala_offset(item, "red") == (1e-4, offset)


def test_escala_offset_pela_data_quando_falta_baseline(fabrica_cena):
    item = fabrica_cena(raster_bands=False).item
    del item.properties["s2:processing_baseline"]
    assert escala_offset(item, "red")[1] == -0.1
    item.datetime = datetime(2021, 6, 1, tzinfo=UTC)
    assert escala_offset(item, "red")[1] == 0.0


def test_selecao_ordena_filtra_e_deduplica(fabrica_cena, talhao_wgs84):
    antiga = fabrica_cena("antiga", dia=5).item
    recente = fabrica_cena("recente", dia=10).item
    duplicada = fabrica_cena("recente-dup", dia=10).item
    duplicada.properties["eo:cloud_cover"] = 30.0
    nublada = fabrica_cena("nublada", dia=8, nuvem_total=True).item

    cenas = selecionar_cenas([antiga, duplicada, recente, nublada], talhao_wgs84, 60)
    assert [c.id for c in cenas] == ["recente", "antiga"]
    assert cenas[0].tile == "23LMD"


def test_selecao_exige_talhao_inteiro_na_pegada(fabrica_cena, talhao_wgs84):
    item = fabrica_cena().item
    deslocado = talhao_wgs84.buffer(0.05)  # ~5 km, maior que o tile sintético
    assert selecionar_cenas([item], deslocado, 100) == []
