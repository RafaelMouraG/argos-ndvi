"""Linha de comando: gera os arquivos do mapa temático e a série temporal em CSV."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from argos import analise
from argos.exportacao import salvar_ndvi, salvar_zonas
from argos.geometria import GeometriaInvalida, carregar_talhao
from argos.raster import ForaDaCena


def _ler_talhao(caminho: Path):
    return carregar_talhao(json.loads(caminho.read_text(encoding="utf-8")))


def _exportar(args: argparse.Namespace) -> None:
    fim = args.fim or date.today()
    inicio = args.inicio or fim - timedelta(days=30)
    relatorio, resultado, zoneamento = analise.analisar(
        _ler_talhao(args.talhao),
        inicio,
        fim,
        max_nuvens_cena=args.max_nuvens_cena,
        max_mascarado_pct=args.max_mascarado,
        modo=args.zoneamento,
        area_minima_ha=args.area_minima,
        talhao_id=args.id,
    )
    args.saida.mkdir(parents=True, exist_ok=True)
    sufixo = relatorio["data_imagem"]
    arquivos = [
        salvar_ndvi(resultado, args.saida / f"ndvi_{sufixo}.tif"),
        salvar_zonas(resultado, zoneamento, args.saida / f"zonas_{sufixo}.geojson"),
    ]
    caminho_relatorio = args.saida / f"relatorio_{sufixo}.json"
    caminho_relatorio.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    arquivos.append(caminho_relatorio)
    print(f"Cena {relatorio['item_id']} ({sufixo}), NDVI médio "
          f"{relatorio['estatisticas_ndvi']['media']:.3f}")
    for arquivo in arquivos:
        print(f"  {arquivo}")


def _serie(args: argparse.Namespace) -> None:
    serie = analise.serie_temporal(
        _ler_talhao(args.talhao),
        args.inicio,
        args.fim or date.today(),
        max_nuvens_cena=args.max_nuvens_cena,
        max_mascarado_pct=args.max_mascarado,
        talhao_id=args.id,
    )
    campos = ["data", "item_id", "satelite", "media", "mediana", "desvio_padrao",
              "pct_mascarado_talhao", "pct_valido"]
    with args.saida.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(serie["pontos"])
    print(f"{len(serie['pontos'])} ponto(s), {len(serie['descartadas'])} cena(s) descartada(s)")
    print(f"  {args.saida}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="argos", description="Análise de NDVI de talhões.")
    sub = parser.add_subparsers(dest="comando", required=True)

    exp = sub.add_parser("exportar", help="NDVI (GeoTIFF), zonas (GeoJSON) e relatório (JSON).")
    exp.add_argument("talhao", type=Path, help="Arquivo GeoJSON do talhão (WGS84).")
    exp.add_argument("--inicio", type=date.fromisoformat)
    exp.add_argument("--fim", type=date.fromisoformat)
    exp.add_argument("--saida", type=Path, default=Path("saida"))
    exp.add_argument("--max-nuvens-cena", type=float, default=60.0)
    exp.add_argument("--max-mascarado", type=float, default=10.0)
    exp.add_argument("--zoneamento", choices=["absoluto", "relativo"], default="absoluto")
    exp.add_argument(
        "--area-minima", type=float, default=0.0, metavar="HA",
        help="Absorve manchas de zona menores que essa área (ex.: 0.5). Padrão: 0 (desligado).",
    )
    exp.add_argument("--id")
    exp.set_defaults(func=_exportar)

    ser = sub.add_parser("serie", help="Série temporal do NDVI em CSV.")
    ser.add_argument("talhao", type=Path)
    ser.add_argument("--inicio", type=date.fromisoformat, required=True)
    ser.add_argument("--fim", type=date.fromisoformat)
    ser.add_argument("--saida", type=Path, default=Path("serie.csv"))
    ser.add_argument("--max-nuvens-cena", type=float, default=80.0)
    ser.add_argument("--max-mascarado", type=float, default=20.0)
    ser.add_argument("--id")
    ser.set_defaults(func=_serie)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (GeometriaInvalida, ForaDaCena, analise.SemImagemDisponivel) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
