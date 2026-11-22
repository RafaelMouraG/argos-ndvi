"""Aplicação FastAPI.

Os endpoints são síncronos (def) de propósito: o rasterio faz I/O bloqueante e o
FastAPI executa handlers síncronos num threadpool, sem travar o event loop.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pystac_client.exceptions import APIError
from rasterio.errors import RasterioIOError

from argos import __version__, analise
from argos.geometria import GeometriaInvalida, carregar_talhao
from argos.raster import ForaDaCena
from argos.schemas import AnaliseRequisicao, AnaliseResposta, SerieRequisicao, SerieResposta

log = logging.getLogger("argos")

app = FastAPI(
    title="Argos NDVI",
    version=__version__,
    description=(
        "Análise de NDVI de talhões com Sentinel-2 L2A via STAC e leitura parcial de COG. "
        "Contém dados modificados do Copernicus Sentinel."
    ),
)


def _erro(status: int, mensagem: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": mensagem})


@app.exception_handler(GeometriaInvalida)
def _geometria_invalida(_: Request, exc: GeometriaInvalida) -> JSONResponse:
    return _erro(422, str(exc))


@app.exception_handler(ForaDaCena)
def _fora_da_cena(_: Request, exc: ForaDaCena) -> JSONResponse:
    return _erro(422, str(exc))


@app.exception_handler(analise.SemImagemDisponivel)
def _sem_imagem(_: Request, exc: analise.SemImagemDisponivel) -> JSONResponse:
    return _erro(404, str(exc))


@app.exception_handler(APIError)
def _erro_catalogo(_: Request, exc: APIError) -> JSONResponse:
    log.exception("Falha no catálogo STAC")
    return _erro(502, "Falha ao consultar o catálogo STAC.")


@app.exception_handler(RasterioIOError)
def _erro_leitura(_: Request, exc: RasterioIOError) -> JSONResponse:
    log.exception("Falha ao ler raster remoto")
    return _erro(502, "Falha ao ler as imagens da cena.")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "versao": __version__}


@app.post("/api/v1/ndvi/analise", response_model=AnaliseResposta)
def analisar(req: AnaliseRequisicao) -> dict:
    assert req.data_inicio is not None and req.data_fim is not None
    relatorio, _, _ = analise.analisar(
        carregar_talhao(req.geometria),
        req.data_inicio,
        req.data_fim,
        max_nuvens_cena=req.max_nuvens_cena,
        max_mascarado_pct=req.max_mascarado_talhao,
        modo=req.zoneamento,
        limiares=req.limiares,
        tolerancia=req.tolerancia_relativa,
        limiar_alerta_pct=req.limiar_alerta_pct,
        talhao_id=req.talhao_id,
    )
    return relatorio


@app.post("/api/v1/ndvi/serie-temporal", response_model=SerieResposta)
def serie_temporal(req: SerieRequisicao) -> dict:
    assert req.data_fim is not None
    return analise.serie_temporal(
        carregar_talhao(req.geometria),
        req.data_inicio,
        req.data_fim,
        max_nuvens_cena=req.max_nuvens_cena,
        max_mascarado_pct=req.max_mascarado_talhao,
        talhao_id=req.talhao_id,
    )
