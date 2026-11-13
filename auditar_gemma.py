"""Inventário de revisão das saídas do Gemma."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "dados"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    report = {}
    for name in ("integral", "gemma_tabelas"):
        folder = ROOT / name
        chunks = read(folder / "trechos.json")
        results_file = folder / "extracoes.json"
        results = read(results_file) if results_file.exists() else []
        results_by_id = {result["chunk_id"]: result for result in results}
        report[name] = {
            "esperados": len(chunks),
            "recebidos": len(results_by_id),
            "pendentes": [row["id"] for row in chunks if row["id"] not in results_by_id],
            "falhas": [row for row in results if "error" in row],
            "sem_relacoes": [
                row["chunk_id"] for row in results
                if "error" not in row and not row.get("relations")
            ],
            "para_revisar": [
                {"chunk_id": row["chunk_id"], **relation}
                for row in results for relation in row.get("relations", [])
            ],
        }
        print(name, len(results_by_id), "/", len(chunks))
    (ROOT / "integral/relatorio_revisao.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
