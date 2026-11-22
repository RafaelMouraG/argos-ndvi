# argos-ndvi

Serviço de análise de NDVI de talhões agrícolas com imagens Sentinel-2 L2A. Recebe o
polígono do talhão em GeoJSON, busca as cenas num catálogo STAC, lê só os pixels do
talhão nos Cloud Optimized GeoTIFFs, mascara nuvens pela SCL e devolve estatísticas,
zonas de manejo em hectares e a série temporal do índice.

## Instalação

Requer Python 3.11 ou superior.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## API

```bash
uvicorn argos.api:app --reload
```

A documentação interativa fica em `http://localhost:8000/docs`.

| Método | Rota | Descrição |
| --- | --- | --- |
| `GET` | `/health` | Verificação do serviço |
| `POST` | `/api/v1/ndvi/analise` | Diagnóstico da cena mais recente com o talhão limpo |
| `POST` | `/api/v1/ndvi/serie-temporal` | NDVI médio e mediano por data no período |

Exemplo de requisição:

```json
{
  "talhao_id": "talhao-norte-01",
  "geometria": { "type": "Polygon", "coordinates": [[[-45.7995, -12.1024], "..."]] },
  "data_inicio": "2026-10-20",
  "data_fim": "2026-11-20",
  "max_mascarado_talhao": 10,
  "zoneamento": "absoluto",
  "limiares": [0.10, 0.30, 0.60]
}
```

Campos principais da resposta:

| Campo | Significado |
| --- | --- |
| `area_total_ha` | Área vetorial do talhão em SIRGAS 2000 / UTM (`src_area`) |
| `pct_mascarado_talhao` | Percentual do talhão descartado pela SCL (nuvem, sombra, cirrus, defeito) |
| `area_valida_ha`, `area_mascarada_ha` | Área dos pixels usados e descartados |
| `correcao_radiometrica` | Escala e offset aplicados para converter DN em reflectância |
| `estatisticas_ndvi` | Média, mediana, mínimo, máximo, desvio padrão, p10 e p90 |
| `zoneamento.zonas` | Área e percentual de cada classe de vigor |
| `alerta` | Preenchido quando a classe de baixo vigor passa de `limiar_alerta_pct`. No modo absoluto, se a mediana do talhão já está em baixo vigor, o alerta é suprimido e vira aviso de estádio inicial |
| `avisos` | Saturação do NDVI, efeito de borda, área mascarada |

## Linha de comando

Gera os arquivos para montar o mapa temático no QGIS:

```bash
argos exportar exemplos/talhao_exemplo.geojson --inicio 2026-10-20 --fim 2026-11-20 \
  --saida saida/ --zoneamento relativo --area-minima 0.5
```

`--area-minima` absorve manchas de zona menores que a área informada (em hectares) pela
classe vizinha dominante, o que remove o efeito "sal e pimenta" da classificação pixel a
pixel. Saída: `ndvi_<data>.tif` (float32 no SRC da cena), `zonas_<data>.geojson` (WGS84) e
`relatorio_<data>.json`.

```bash
argos serie exemplos/talhao_exemplo.geojson --inicio 2026-10-01 --saida serie.csv
```

O arquivo `exemplos/talhao_exemplo.geojson` é um polígono fictício de cerca de 47 ha
perto de Luís Eduardo Magalhães (BA), só para teste.

## Como funciona

1. Valida o GeoJSON (WGS84) e calcula a área em SIRGAS 2000 / UTM.
2. Busca cenas da coleção `sentinel-2-c1-l2a` no Earth Search e mantém só as que contêm
   o talhão inteiro.
3. Reprojeta o polígono para o SRC da cena e calcula uma janela alinhada às grades de
   10 m e 20 m.
4. Lê a SCL da janela (range requests no COG). Se o talhão estiver mascarado acima do
   limite, passa para a cena anterior sem baixar as outras bandas.
5. Lê B04 e B08, aplica escala e offset do `raster:bands` e calcula o NDVI só nos
   pixels válidos.
6. Calcula estatísticas, classifica as zonas e converte a contagem de pixels em hectares.

Guarde os polígonos reais em `talhoes/`: a pasta é ignorada pelo git para que as
coordenadas das propriedades não vão para o repositório.

Variáveis de ambiente: `ARGOS_PROVEDOR`, `ARGOS_MAX_AREA_HA`, `ARGOS_MAX_WORKERS`,
`ARGOS_MAX_CENAS_SERIE`.

## Dados

Contém dados modificados do Copernicus Sentinel, processados pelo Argos. As imagens
Sentinel-2 são distribuídas gratuitamente pelo programa Copernicus; o catálogo STAC e
os COGs vêm do Earth Search (Element 84) no AWS Open Data.
