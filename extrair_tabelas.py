"""Exporta células com coordenadas para conferência contra o PDF."""
import argparse
import json
from pathlib import Path
import pdfplumber

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="?", type=Path, help="Caminho do PDF original.")
    args = parser.parse_args()
    source = args.pdf
    if source is None:
        originals = list(ROOT.glob("Minist*.pdf"))
        if len(originals) != 1:
            parser.error("Informe explicitamente o caminho do PDF original.")
        source = originals[0]
    tables = []
    with pdfplumber.open(source) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            for index, table in enumerate(page.find_tables(), 1):
                rows = [
                    {"cells": cells, "boxes": row.cells}
                    for cells, row in zip(table.extract(), table.rows, strict=True)
                ]
                tables.append({
                    "page": number, "table": index, "box": table.bbox,
                    "rows": rows, "review": "pendente",
                })
    path = ROOT / "dados/integral/tabelas.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tables, ensure_ascii=False, indent=2), encoding="utf-8")
    print(len(tables), "blocos;", sum(len(t["rows"]) for t in tables), "linhas")


if __name__ == "__main__":
    main()
