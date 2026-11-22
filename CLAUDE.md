# Argos NDVI

Microsserviço de análise de NDVI de talhões com imagens Sentinel-2 L2A. Faz parte do
ecossistema do Talos (plataforma de gestão de fazendas), mas roda como serviço
independente, com contrato REST próprio. Também é o estudo de caso da Atividade 09 da
disciplina Fundamentos de Geoprocessamento (PUC Minas): os arquivos gerados pela CLI
alimentam o mapa temático feito no QGIS.

Caso de uso principal: talhões de soja no oeste baiano (fuso UTM 23S).

## Comandos

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

pytest                      # testes com rasters sintéticos, sem rede
ruff check .
uvicorn argos.api:app --reload    # docs em http://localhost:8000/docs
argos exportar exemplos/talhao_exemplo.geojson --saida saida/
argos serie exemplos/talhao_exemplo.geojson --inicio 2026-10-01 --saida serie.csv
```

## Módulos (`src/argos/`)

| Módulo | Responsabilidade |
| --- | --- |
| `config.py` | Provedores STAC, classes SCL mascaradas, opções do GDAL, limites |
| `geometria.py` | Validação do GeoJSON, reprojeção de vetores, área em SIRGAS 2000 / UTM |
| `catalogo.py` | Busca STAC, seleção de cenas, escala e offset radiométricos |
| `raster.py` | Janela alinhada à grade, leitura parcial de COG, máscara do polígono |
| `ndvi.py` | Reflectância, NDVI, estatísticas e zoneamento (só numpy, sem I/O) |
| `analise.py` | Orquestração do pipeline e montagem do relatório |
| `exportacao.py` | GeoTIFF de NDVI e GeoJSON de zonas para o QGIS |
| `api.py`, `schemas.py` | FastAPI e contratos Pydantic |
| `cli.py` | Comandos `argos exportar` e `argos serie` |

## Decisões técnicas

Não reverter sem discutir. Cada item tem um motivo técnico.

1. **Provedor padrão: Earth Search v1, coleção `sentinel-2-c1-l2a`.** Assets `red`
   (B04), `nir` (B08) e `scl`. Os assets trazem `raster:bands` com `scale` 0.0001 e
   `offset` -0.1.
2. **Correção radiométrica obrigatória.** `rho = DN * escala + offset`, lida do
   `raster:bands`. Fallback: `s2:processing_baseline` >= 04.00 implica offset -0.1; sem
   baseline, a data (25/01/2022). Sem essa correção o NDVI sai errado (0,80 vira 0,57).
   Reflectância negativa é truncada em 0.
3. **Reprojetar o vetor, nunca o raster.** O recorte é feito na grade nativa da cena
   (WGS84 / UTM). A área oficial do talhão é calculada em SIRGAS 2000 / UTM do fuso do
   centroide. A área das zonas é a contagem de pixels vezes a área do pixel.
4. **SCL alinhada, sem interpolação.** A janela é alinhada à grade de 20 m e cada pixel
   da SCL é replicado em 2 x 2. Classes mascaradas: 0, 1, 3, 8, 9, 10.
5. **Nuvens medidas dentro do talhão.** `eo:cloud_cover` (cena inteira) só pré-filtra a
   busca. A decisão de aceitar a cena usa o percentual do talhão mascarado pela SCL. A
   SCL é lida antes de RED e NIR para não baixar bandas de cenas descartadas.
6. **Talhão inteiro dentro de uma cena.** Só são usadas cenas cuja pegada contém o
   polígono. Não há mosaico entre tiles na v1.
7. **Endpoints com `def`, não `async def`.** O rasterio faz I/O bloqueante. A série
   temporal usa `ThreadPoolExecutor`, com datasets abertos por thread.
8. **Zoneamento absoluto (limiares configuráveis, padrão 0,10 / 0,30 / 0,60) ou
   relativo à mediana do talhão.** Os limiares fixos dependem da cultura e do estádio.
9. **Atribuição Copernicus em toda saída** (JSON, GeoTIFF e GeoJSON).

## Testes

`tests/conftest.py` gera uma cena sintética (tile de 2 km em EPSG:32723, talhão de
64 ha, faixa de baixo vigor de 16 ha e 1 ha de nuvem) e substitui a busca STAC por
`catalogo.selecionar_cenas` sobre itens locais. Os testes não acessam a rede. Mudanças
no pipeline devem manter os valores esperados ou justificar a alteração.

## Convenções

- Código, mensagens de erro e documentação em português.
- Não usar travessão (—) em textos e documentação.
- Não fazer commit nem criar branch sem perguntar antes.
- Não adicionar autoria ou atribuição do Claude em commits, branches ou PRs.

## Limitações conhecidas e próximos passos

- NDRE com o asset `rededge1` (B05, 20 m) para reduzir a saturação do NDVI em dossel
  fechado.
- Mosaico de cenas para talhões na borda entre tiles.
- Outros provedores (Brazil Data Cube, Planetary Computer com assinatura de URLs).
- Imagem PNG colorizada na resposta.
- Cache de resultados por talhão e cena; autenticação.
