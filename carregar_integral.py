"""Carga reproduzível do inventário e das relações candidatas."""
import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compacta", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    folder = ROOT / ("dados/compacta" if args.compacta else "dados/integral")
    chunks = json.loads((folder / "trechos.json").read_text(encoding="utf-8"))
    extractions_file = folder / "extracoes.json"
    extractions = (json.loads(extractions_file.read_text(encoding="utf-8"))
                   if extractions_file.exists() or not args.compacta else [])
    pilot_file = folder / "relacoes_piloto_validadas.json"
    pilot = json.loads(pilot_file.read_text(encoding="utf-8")) if args.compacta and pilot_file.exists() else []
    relations = []
    for result in extractions + pilot:
        if result.get("status") == "reprovado_na_revisao_semantica":
            continue
        entities = {item["name"]: item for item in result.get("entities", [])}
        for relation in result.get("relations", []):
            relations.append({
                "chunk": result["chunk_id"], "source": entities[relation["source"]],
                "target": entities[relation["target"]], "type": relation["type"],
                "evidence": relation["evidence"],
            })
    with GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    ) as driver:
        database = "doacao-compacta" if args.compacta else os.getenv("NEO4J_DATABASE", "neo4j")
        if args.compacta:
            driver.execute_query(
                "CREATE CONSTRAINT escopo_documental_id IF NOT EXISTS "
                "FOR (e:EscopoDocumental) REQUIRE e.id IS UNIQUE", database_=database)
            driver.execute_query(
                "CREATE DATABASE `doacao-compacta` IF NOT EXISTS WAIT 30 SECONDS",
                database_="system",
            )
        driver.execute_query(
            "CREATE CONSTRAINT trecho_integral_id IF NOT EXISTS "
            "FOR (t:TrechoIntegral) REQUIRE t.id IS UNIQUE", database_=database)
        driver.execute_query(
            "CREATE CONSTRAINT entidade_candidata_id IF NOT EXISTS "
            "FOR (e:EntidadeCandidata) REQUIRE e.canonical_key IS UNIQUE", database_=database)
        if args.compacta:
            driver.execute_query(
                "CREATE INDEX trecho_referencia IF NOT EXISTS "
                "FOR (t:TrechoIntegral) ON (t.annex, t.article)", database_=database)
            driver.execute_query(
                "CREATE FULLTEXT INDEX trecho_texto IF NOT EXISTS "
                "FOR (t:TrechoIntegral) ON EACH [t.text]", database_=database)
        with driver.session(database=database) as session:
            def ingest(tx):
                tx.run("""
                    UNWIND $chunks AS row
                    MERGE (t:TrechoIntegral {id: row.id})
                    SET t += row
                    """, chunks=chunks).consume()
                if args.compacta:
                    tx.run("""
                        MATCH (t:TrechoIntegral)
                        WITH t, t.annex + '/' + coalesce(t.internal_annex, '') +
                            '/' + coalesce(toString(t.article), '') AS scope
                        MERGE (e:EscopoDocumental {id: scope})
                        SET e.anexo = t.annex, e.anexo_interno = t.internal_annex,
                            e.artigo = t.article
                        MERGE (t)-[:PERTENCE_A]->(e)
                        MERGE (d:DocumentoFonte {nome: t.source_pdf})
                        MERGE (e)-[:PARTE_DE]->(d)
                        """).consume()
                tx.run("""
                    UNWIND $relations AS row
                    MATCH (t:TrechoIntegral {id: row.chunk})
                    MERGE (a:EntidadeCandidata {canonical_key: row.source.canonical_key})
                    SET a.name = row.source.name, a.type = row.source.type
                    MERGE (b:EntidadeCandidata {canonical_key: row.target.canonical_key})
                    SET b.name = row.target.name, b.type = row.target.type
                    MERGE (a)-[:RELACAO_CANDIDATA {tipo: row.type, trecho: row.chunk,
                           evidencia: row.evidence}]->(b)
                    MERGE (a)-[:TEM_EVIDENCIA]->(t)
                    MERGE (b)-[:TEM_EVIDENCIA]->(t)
                    """, relations=relations).consume()
                if args.compacta:
                    tx.run("""
                        MATCH (a:EntidadeCandidata)-[short:RELACAO_CANDIDATA]->(b:EntidadeCandidata)
                        MATCH (a)-[full:RELACAO_CANDIDATA]->(b)
                        WHERE short.trecho = full.trecho AND short.tipo = full.tipo
                          AND size(full.evidencia) > size(short.evidencia)
                          AND full.evidencia STARTS WITH short.evidencia
                        WITH DISTINCT short
                        DELETE short
                        """).consume()
                return tx.run("""
                    MATCH (t:TrechoIntegral)
                    WITH count(t) AS trechos
                    OPTIONAL MATCH (:EntidadeCandidata)-[r:RELACAO_CANDIDATA]->()
                    RETURN trechos, count(r) AS candidatas
                    """).single().data()

            first = session.execute_write(ingest)
            second = session.execute_write(ingest)
            assert first == second and second["trechos"] == len(chunks)
            print(f"Resultados Gemma: {len(extractions)}/{len(chunks)}")
            print("Carga e recarga:", first, second)


if __name__ == "__main__":
    main()
