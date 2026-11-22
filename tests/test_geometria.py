import pytest
from shapely.geometry import mapping

from argos.geometria import GeometriaInvalida, area_ha, carregar_talhao, crs_sirgas_utm


def test_area_do_talhao_em_sirgas_2000_utm_23s(talhao_wgs84):
    area, crs = area_ha(talhao_wgs84)
    assert crs.to_epsg() == 31983
    assert area == pytest.approx(64.0, abs=0.01)


def test_fuso_do_centroide():
    assert crs_sirgas_utm(carregar_talhao(_quadrado(-45.8, -12.1))).to_epsg() == 31983
    assert crs_sirgas_utm(carregar_talhao(_quadrado(-47.9, -15.8))).to_epsg() == 31983
    assert crs_sirgas_utm(carregar_talhao(_quadrado(-49.3, -25.4))).to_epsg() == 31982


def test_aceita_feature_e_feature_collection(talhao_wgs84):
    geometria = mapping(talhao_wgs84)
    feature = {"type": "Feature", "properties": {}, "geometry": geometria}
    colecao = {"type": "FeatureCollection", "features": [feature]}
    for entrada in (geometria, feature, colecao):
        assert carregar_talhao(entrada).equals(talhao_wgs84)


@pytest.mark.parametrize(
    "entrada, trecho",
    [
        ({"type": "Point", "coordinates": [-45.8, -12.1]}, "não suportado"),
        ({"type": "FeatureCollection", "features": []}, "exatamente um"),
        (
            {"type": "Polygon", "coordinates": [[[400500, 8698500], [401300, 8698500],
                                                 [401300, 8699300], [400500, 8698500]]]},
            "WGS84",
        ),
        (
            {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]},
            "inválida",
        ),
    ],
)
def test_rejeita_geometrias_problematicas(entrada, trecho):
    with pytest.raises(GeometriaInvalida, match=trecho):
        carregar_talhao(entrada)


def _quadrado(lon: float, lat: float, d: float = 0.005) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d],
                         [lon, lat]]],
    }
