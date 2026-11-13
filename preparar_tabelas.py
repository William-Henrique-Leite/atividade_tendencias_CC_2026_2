"""Prepara blocos tabulares para extração, preservando células e proveniência."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    folder = ROOT / "dados/integral"
    tables = json.loads((folder / "tabelas.json").read_text(encoding="utf-8"))
    chunks = []
    for table in tables:
        page = table["page"]
        index = table["table"]
        rows = [row["cells"] for row in table["rows"]]
        context = []
        if (page, index) == (52, 1):
            previous = next(t for t in tables if (t["page"], t["table"]) == (51, 3))
            context = [row["cells"] for row in previous["rows"][:2]]
        for offset in range(0, len(rows), 8):
            # Reenvia as primeiras linhas para preservar títulos e cabeçalhos locais.
            payload = {
                "contexto_pagina_anterior": context,
                "inicio_do_bloco": rows[:2],
                "linhas_alvo": rows[offset:offset + 8],
            }
            chunks.append({
                "id": f"tabela/p{page:02d}/{index}/{offset + 1}",
                "pages": [51, 52] if context else [page],
                "article": None,
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            })
    output = folder / "trechos_tabelas.json"
    output.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(len(chunks), "trechos tabulares")


if __name__ == "__main__":
    main()
