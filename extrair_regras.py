"""Structure source-backed rules and export an import script for Neo4j."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    situation: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    effect: str = Field(min_length=1)


class Rules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[Rule] = Field(min_length=1)


# Reference annotations for the first lot. The source text remains the authority.
REFERENCE_TOPICS = {
    (38, None): "Frequencia de doacoes",
    (38, 1): "Intervalo entre doacoes",
    (38, 2): "Doacao autologa",
    (39, None): "Idade",
    (39, 1): "Consentimento do responsavel",
    (39, 2): "Consentimento do responsavel",
    (39, 3): "Primeira doacao",
    (39, 4): "Excecao de idade",
    (39, 5): "Doacao de repeticao",
    (40, None): "Peso",
    (40, 1): "Peso",
    (40, 2): "Perda de peso",
}


def extract_with_ollama(chunk: dict, context: str, model: str) -> Rules:
    payload = {
        "model": model,
        "stream": False,
        "format": Rules.model_json_schema(),
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": (
                "Extraia regras da portaria em portugues. Separe condicao e efeito. "
                "Preserve prazos, unidades e ressalvas. Extraia somente afirmacoes do "
                "trecho-alvo. Use o contexto somente para interpretar referencias."
            )},
            {"role": "user", "content": f"Contexto: {context}\nTrecho-alvo: {chunk['text']}"},
        ],
    }
    request = Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=180) as response:
        result = json.load(response)
    return Rules.model_validate_json(result["message"]["content"])


def build_rules(corpus: dict, model: str | None) -> list[dict]:
    chunks = corpus["chunks"]
    results = {}
    for chunk in chunks:
        key = (chunk["article"], chunk["paragraph"])
        if key not in REFERENCE_TOPICS:
            continue
        topic = REFERENCE_TOPICS[key]
        if model:
            context = " ".join(
                item["text"] for item in chunks if item["article_id"] == chunk["article_id"]
            )
            extracted = extract_with_ollama(chunk, context, model).rules
        else:
            extracted = [Rule(
                situation=topic,
                condition=f"Consultar as condicoes do art. {chunk['article']}.",
                effect=chunk["text"],
            )]
        for rule in extracted:
            data = rule.model_dump()
            fingerprint = hashlib.sha256(
                json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()[:16]
            rule_id = f"{chunk['id']}/regra-{fingerprint}"
            results[rule_id] = {
                "id": rule_id,
                "chunk_id": chunk["id"],
                "situation_id": topic.lower().replace(" ", "-"),
                **data,
                "evidence": chunk["text"],
                "status": "pendente_de_revisao" if model else "referencia_documental",
            }
    return list(results.values())


def cypher_map(record: dict) -> str:
    fields = (
        f"{name}: {json.dumps(value, ensure_ascii=False)}" for name, value in record.items()
    )
    return "{" + ", ".join(fields) + "}"


def export_cypher(corpus: dict, rules: list[dict]) -> str:
    doc = corpus["document"]
    chunks = corpus["chunks"]
    chunk_rows = ",\n".join(map(cypher_map, chunks))
    rule_rows = ",\n".join(map(cypher_map, rules))
    return f"""CREATE CONSTRAINT documento_id IF NOT EXISTS FOR (n:Documento) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT secao_id IF NOT EXISTS FOR (n:Secao) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT trecho_id IF NOT EXISTS FOR (n:Trecho) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT regra_id IF NOT EXISTS FOR (n:Regra) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT situacao_id IF NOT EXISTS FOR (n:Situacao) REQUIRE n.id IS UNIQUE;
CREATE INDEX trecho_artigo IF NOT EXISTS FOR (n:Trecho) ON (n.article);
CREATE FULLTEXT INDEX trecho_texto IF NOT EXISTS FOR (n:Trecho) ON EACH [n.text];

UNWIND [{chunk_rows}] AS row
MERGE (d:Documento {{id: {json.dumps(doc["id"])}}})
SET d += {cypher_map(doc)}
MERGE (s:Secao {{id: d.id + '/' + row.section}})
SET s.nome = row.section
MERGE (d)-[:CONTEM]->(s)
MERGE (t:Trecho {{id: row.id}})
SET t += row
MERGE (s)-[:CONTEM]->(t);

UNWIND [{rule_rows}] AS row
MATCH (t:Trecho {{id: row.chunk_id}})
MERGE (s:Situacao {{id: row.situation_id}})
ON CREATE SET s.nome = row.situation
MERGE (r:Regra {{id: row.id}})
SET r += row
MERGE (s)-[:TEM_REGRA]->(r)
MERGE (r)-[:FUNDAMENTADA_EM]->(t)
MERGE (t)-[:MENCIONA]->(s);
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("dados/trechos.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("dados"))
    parser.add_argument("--ollama-model", help="Modelo ja instalado no Ollama local")
    args = parser.parse_args()
    corpus = json.loads(args.input.read_text(encoding="utf-8"))
    rules = build_rules(corpus, args.ollama_model)
    args.output_dir.mkdir(exist_ok=True, parents=True)
    (args.output_dir / "regras.json").write_text(
        json.dumps({"model": args.ollama_model, "rules": rules}, ensure_ascii=False, indent=2)
        + "\n", encoding="utf-8"
    )
    if not args.ollama_model:
        (args.output_dir / "importar.cypher").write_text(
            export_cypher(corpus, rules), encoding="utf-8"
        )
    print(f"{len(rules)} registros em {args.output_dir}")


if __name__ == "__main__":
    main()
