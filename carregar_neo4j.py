"""Carrega e verifica o grafo documental na instancia configurada."""
import os
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parent


def main():
    load_dotenv(ROOT / ".env")
    with GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
    ) as driver:
        driver.verify_connectivity()
        with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            script = (ROOT / "dados/importar.cypher").read_text(encoding="utf-8")
            # Os textos podem conter ponto e virgula. As instrucoes terminam em ; seguido de quebra.
            import re
            statements = re.split(r";\s*\n", script)
            for statement in statements:
                if statement.strip():
                    session.run(statement.rstrip().removesuffix(";")).consume()
            result = session.run(
                "MATCH (n) RETURN labels(n) AS tipos, count(*) AS quantidade"
            )
            print([record.data() for record in result])


if __name__ == "__main__":
    main()
