"""Indexa trechos do PDF no Neo4j para busca vetorial."""
import argparse
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase
from lm_studio import embeddings

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compacta", action="store_true")
    parser.add_argument("--limite", type=int)
    args = parser.parse_args()
    if args.limite is not None and args.limite < 1:
        parser.error("--limite deve ser maior que zero.")
    load_dotenv(ROOT / ".env")
    folder = ROOT / ("dados/compacta" if args.compacta else "dados/integral")
    chunks = json.loads((folder / "trechos.json").read_text(encoding="utf-8"))
    with GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(
        os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]
    )) as driver:
        database = "doacao-compacta" if args.compacta else os.getenv("NEO4J_DATABASE", "neo4j")
        driver.execute_query(
            "CREATE VECTOR INDEX trecho_vetor IF NOT EXISTS FOR (t:TrechoIntegral) "
            "ON (t.embedding) OPTIONS {indexConfig: {"
            "`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}",
            database_=database,
        )
        with driver.session(database=database) as session:
            pending = session.run(
                "MATCH (t:TrechoIntegral) WHERE t.embedding IS NULL RETURN t.id AS id ORDER BY id"
            ).value()[:args.limite]
            by_id = {chunk["id"]: chunk for chunk in chunks}
            for start in range(0, len(pending), 8):
                batch = [by_id[item] for item in pending[start:start + 8] if item in by_id]
                if not batch:
                    continue
                vectors = embeddings([item["text"] for item in batch])
                session.run(
                    "UNWIND $rows AS row MATCH (t:TrechoIntegral {id: row.id}) "
                    "SET t.embedding = row.vector",
                    rows=[{"id": chunk["id"], "vector": vector}
                          for chunk, vector in zip(batch, vectors, strict=True)],
                ).consume()
                print(f"{min(start + 8, len(pending))}/{len(pending)}", flush=True)


if __name__ == "__main__":
    main()
