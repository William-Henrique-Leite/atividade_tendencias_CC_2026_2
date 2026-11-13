"""Revisa relações e possíveis omissões por trecho, com checkpoints."""
import hashlib
import json
from pathlib import Path

from lm_studio import CHAT_MODEL, chat

ROOT = Path(__file__).resolve().parent / "dados"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    destination = ROOT / "integral/revisao_semantica"
    destination.mkdir(exist_ok=True)
    for name in ("integral", "gemma_tabelas"):
        folder = ROOT / name
        sources = {row["id"]: row["text"] for row in read(folder / "trechos.json")}
        for row in read(folder / "extracoes.json"):
            if "error" in row:
                continue
            key = row["chunk_id"]
            relations = row.get("relations", [])
            payload = json.dumps({"fonte": sources[key], "relacoes": relations},
                                 ensure_ascii=False)
            digest = hashlib.sha256((CHAT_MODEL + payload).encode()).hexdigest()
            output = destination / f"{digest}.json"
            if output.exists():
                continue
            response = chat([
                {"role": "system", "content": (
                    "Revise a fidelidade semantica a fonte. Para cada relacao, na ordem, "
                    "retorne sustentada, contradita ou insuficiente e justifique. Confira "
                    "direcao, sujeitos, negacoes, prazos, condicoes e excecoes. Quando "
                    "a lista estiver vazia, informe se ha possivel omissao e explique."
                )},
                {"role": "user", "content": payload},
            ])
            output.write_text(json.dumps({
                "chunk_id": key, "model": CHAT_MODEL, "relations": relations,
                "review": response, "status": "parecer_automatico",
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            print(key, flush=True)


if __name__ == "__main__":
    main()
