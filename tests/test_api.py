from fastapi.testclient import TestClient
from shapely.geometry import mapping

from argos.api import app

cliente = TestClient(app)


def _corpo(talhao, **extra):
    return {
        "talhao_id": "talhao-01",
        "geometria": mapping(talhao),
        "data_inicio": "2026-11-01",
        "data_fim": "2026-11-20",
        **extra,
    }


def test_health():
    assert cliente.get("/health").json()["status"] == "ok"


def test_analise_ok(fabrica_cena, catalogo_falso, talhao_wgs84):
    catalogo_falso([fabrica_cena().item])
    resposta = cliente.post("/api/v1/ndvi/analise", json=_corpo(talhao_wgs84))
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["talhao_id"] == "talhao-01"
    assert corpo["area_total_ha"] == 64.0
    assert {z["classe"] for z in corpo["zoneamento"]["zonas"]} >= {"baixo_vigor", "alto_vigor"}


def test_analise_sem_imagem_retorna_404(catalogo_falso, talhao_wgs84):
    catalogo_falso([])
    resposta = cliente.post("/api/v1/ndvi/analise", json=_corpo(talhao_wgs84))
    assert resposta.status_code == 404


def test_geometria_invalida_retorna_422():
    corpo = {"geometria": {"type": "Point", "coordinates": [-45.8, -12.1]}}
    resposta = cliente.post("/api/v1/ndvi/analise", json=corpo)
    assert resposta.status_code == 422
    assert "não suportado" in resposta.text


def test_limiares_fora_de_ordem_retornam_422(talhao_wgs84):
    resposta = cliente.post(
        "/api/v1/ndvi/analise", json=_corpo(talhao_wgs84, limiares=[0.6, 0.3, 0.1])
    )
    assert resposta.status_code == 422


def test_serie_temporal_ok(fabrica_cena, catalogo_falso, talhao_wgs84):
    catalogo_falso([fabrica_cena("a", dia=5).item, fabrica_cena("b", dia=10).item])
    resposta = cliente.post("/api/v1/ndvi/serie-temporal", json=_corpo(talhao_wgs84))
    assert resposta.status_code == 200, resposta.text
    assert len(resposta.json()["pontos"]) == 2


def test_serie_rejeita_periodo_longo(talhao_wgs84):
    corpo = _corpo(talhao_wgs84, data_inicio="2024-01-01", data_fim="2026-01-01")
    assert cliente.post("/api/v1/ndvi/serie-temporal", json=corpo).status_code == 422
