"""Contratos de entrada e saída da API."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from argos.geometria import carregar_talhao

MAX_DIAS_ANALISE = 365
MAX_DIAS_SERIE = 400


class _BaseTalhao(BaseModel):
    talhao_id: str | None = Field(default=None, max_length=120)
    geometria: dict[str, Any] = Field(
        description="Polygon, MultiPolygon, Feature ou FeatureCollection com um talhão, em WGS84."
    )

    @field_validator("geometria")
    @classmethod
    def _validar_geometria(cls, valor: dict[str, Any]) -> dict[str, Any]:
        carregar_talhao(valor)  # GeometriaInvalida herda de ValueError
        return valor


class AnaliseRequisicao(_BaseTalhao):
    data_inicio: date | None = Field(default=None, description="Padrão: 30 dias antes do fim.")
    data_fim: date | None = Field(default=None, description="Padrão: hoje.")
    max_nuvens_cena: float = Field(default=60.0, ge=0, le=100)
    max_mascarado_talhao: float = Field(default=10.0, ge=0, le=100)
    zoneamento: Literal["absoluto", "relativo"] = "absoluto"
    limiares: tuple[float, float, float] = (0.10, 0.30, 0.60)
    tolerancia_relativa: float = Field(default=0.15, gt=0, lt=1)
    limiar_alerta_pct: float = Field(default=10.0, ge=0, le=100)

    @field_validator("limiares")
    @classmethod
    def _limiares_crescentes(cls, v: tuple[float, float, float]) -> tuple[float, float, float]:
        if not (-1 <= v[0] < v[1] < v[2] <= 1):
            raise ValueError("Os limiares devem ser crescentes e estar entre -1 e 1.")
        return v

    @model_validator(mode="after")
    def _periodo(self) -> AnaliseRequisicao:
        self.data_fim = self.data_fim or date.today()
        self.data_inicio = self.data_inicio or self.data_fim - timedelta(days=30)
        if self.data_inicio > self.data_fim:
            raise ValueError("data_inicio é posterior a data_fim.")
        if (self.data_fim - self.data_inicio).days > MAX_DIAS_ANALISE:
            raise ValueError(f"O período da análise não pode passar de {MAX_DIAS_ANALISE} dias.")
        return self


class SerieRequisicao(_BaseTalhao):
    data_inicio: date
    data_fim: date | None = None
    max_nuvens_cena: float = Field(default=80.0, ge=0, le=100)
    max_mascarado_talhao: float = Field(default=20.0, ge=0, le=100)

    @model_validator(mode="after")
    def _periodo(self) -> SerieRequisicao:
        self.data_fim = self.data_fim or date.today()
        if self.data_inicio > self.data_fim:
            raise ValueError("data_inicio é posterior a data_fim.")
        if (self.data_fim - self.data_inicio).days > MAX_DIAS_SERIE:
            raise ValueError(f"O período da série não pode passar de {MAX_DIAS_SERIE} dias.")
        return self


class Estatisticas(BaseModel):
    media: float
    mediana: float
    minimo: float
    maximo: float
    desvio_padrao: float
    p10: float
    p90: float


class ZonaResumo(BaseModel):
    classe: str
    faixa: str
    area_ha: float
    percentual: float = Field(description="Percentual da área válida.")


class ZoneamentoResposta(BaseModel):
    modo: Literal["absoluto", "relativo"]
    zonas: list[ZonaResumo]


class Correcao(BaseModel):
    escala: float
    offset: float


class AnaliseResposta(BaseModel):
    talhao_id: str | None
    data_imagem: date
    item_id: str
    tile: str
    satelite: str
    cobertura_nuvens_cena_pct: float | None = Field(
        description="eo:cloud_cover da cena inteira (só usado como pré-filtro)."
    )
    pct_mascarado_talhao: float = Field(
        description="Percentual do talhão descartado pela SCL (nuvem, sombra, cirrus, defeito)."
    )
    area_total_ha: float = Field(description="Área vetorial do talhão em SIRGAS 2000 / UTM.")
    src_area: str
    area_valida_ha: float
    area_mascarada_ha: float
    correcao_radiometrica: dict[str, Correcao]
    estatisticas_ndvi: Estatisticas
    zoneamento: ZoneamentoResposta
    alerta: str | None
    avisos: list[str]
    atribuicao: str


class PontoSerie(BaseModel):
    data: date
    item_id: str
    satelite: str
    media: float
    mediana: float
    desvio_padrao: float
    pct_mascarado_talhao: float
    pct_valido: float


class CenaDescartada(BaseModel):
    data: date
    item_id: str
    pct_mascarado_talhao: float


class Periodo(BaseModel):
    inicio: date
    fim: date


class SerieResposta(BaseModel):
    talhao_id: str | None
    area_total_ha: float
    src_area: str
    periodo: Periodo
    pontos: list[PontoSerie]
    descartadas: list[CenaDescartada]
    atribuicao: str | None
