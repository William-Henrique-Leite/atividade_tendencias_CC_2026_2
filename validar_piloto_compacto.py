"""Estrutura relações verificáveis diretamente a partir do inventário."""
import json
import re

from pipeline_gemma import ROOT, normalized


def main():
    folder = ROOT / "dados/compacta"
    chunks = {row["id"]: row for row in json.loads(
        (folder / "trechos.json").read_text(encoding="utf-8")
    )}
    activity = chunks["I/art-51/0070"]
    medication = chunks["IV/interno-3/texto/0369"]
    prohibition = chunks["I/art-203/0259"]
    activity_text = " ".join(activity["text"].split())
    inciso = re.search(
        r"§ 2º Podem ser consideradas (.+?) como, por exemplo:\s+I - ([^;]+);",
        activity_text,
    )
    record = re.split(r"\n(?=Medicamento — )", medication["text"], maxsplit=1)[0]
    record = " ".join(record.split())
    fields = re.fullmatch(
        r"Medicamento — (.+?) · Tempo de inaptidão — (.+)", record
    )
    prohibition_text = " ".join(prohibition["text"].split())
    exception = re.fullmatch(
        r"Art\. 203\. (Nenhum medicamento será .+?), exceto a (.+?), (em casos excepcionais)\.",
        prohibition_text,
    )
    if not inciso or not fields or not exception:
        raise ValueError("Estrutura esperada ausente nos trechos do piloto.")

    relations = [
        (activity, inciso[2], "atividade", inciso[1], "categoria_de_risco",
         "E_EXEMPLO_DE", inciso[0]),
        (medication, fields[1], "medicamento", fields[2], "criterio_de_inaptidao",
         "TEM_CRITERIO_DE_INAPTIDAO", record),
        (prohibition, exception[2], "solucao", exception[1], "regra",
         "E_EXCECAO_A", exception[0]),
        (prohibition, exception[2], "solucao", exception[3], "condicao",
         "EXCECAO_LIMITADA_A", exception[0]),
    ]
    tables = json.loads((ROOT / "dados/integral/tabelas.json").read_text(encoding="utf-8"))
    prefixes = {
        "II": {"causas de inaptidão temporária": "condicao_clinica"},
        "III": {"cirurgias": "cirurgia", "procedimento odontológico": "procedimento_odontologico"},
        "IV": {"medicamento": "medicamento"},
        "V": {"vacina": "vacina", "soro": "soro"},
    }
    for table in tables:
        candidates = [
            chunk for chunk in chunks.values()
            if table["page"] in chunk["original_pages"] and chunk["annex"] in {*prefixes, "VII", "VIII"}
        ]
        for row in table["rows"]:
            cells = row["cells"]
            if len(cells) == 2 and all(cells):
                analysis, value = (" ".join(cell.split()) for cell in cells)
                evidence = f"Análises — {analysis} · Valores esperados — {value}"
                for chunk in candidates:
                    if chunk["annex"] != "VII" or normalized(evidence) not in normalized(chunk["text"]):
                        continue
                    preceding = normalized(chunk["text"]).split(normalized(evidence), 1)[0]
                    offset = len(preceding)
                    component = chunk.get("inherited_table_heading", "")
                    for match in re.finditer(r"^([^\n]+)\nAnálises · Valores esperados", chunk["text"], re.MULTILINE):
                        if len(normalized(chunk["text"][:match.start()])) < offset:
                            component = match[1]
                    if component:
                        relations.append((chunk, f"{component} · {analysis}", "analise_de_hemocomponente",
                                          value, "valor_esperado", "TEM_VALOR_ESPERADO", evidence))
            if len(cells) == 3 and all(cells):
                parameter, specification, frequency = (" ".join(cell.split()) for cell in cells)
                for chunk in candidates:
                    if chunk["annex"] != "VIII":
                        continue
                    for label in ("Parâmetros", "Reagentes"):
                        evidence = f"{label} — {parameter} · Especificações — {specification} · Frequência — {frequency}"
                        if normalized(evidence) in normalized(chunk["text"]):
                            relations.append((chunk, parameter, "parametro_de_controle",
                                              f"{specification} · Frequência — {frequency}",
                                              "criterio_de_qualidade", "TEM_CRITERIO_DE_QUALIDADE", evidence))
            if len(cells) == 1 and cells[0] and table["page"] in (48, 49):
                entry = " ".join(cells[0].split())
                for chunk in candidates:
                    if chunk["annex"] != "II":
                        continue
                    definitive = chunk["text"].split("B. PRINCIPAIS CAUSAS", 1)[0]
                    heading = chunk.get("inherited_table_heading", "")
                    if "INAPTIDÃO DEFINITIVA" not in heading:
                        heading = next((line for line in definitive.splitlines()
                                        if line.startswith("A - PRINCIPAIS CAUSAS DE INAPTIDÃO DEFINITIVA")), "")
                        if heading:
                            definitive = definitive.split(heading, 1)[1]
                    if heading and normalized(entry) in normalized(definitive):
                        relations.append((chunk, entry, "condicao_clinica", heading,
                                          "lista_de_triagem", "LISTADO_EM", entry))
            if len(cells) != 2 or not all(cells):
                continue
            source, target = (" ".join(cell.split()) for cell in cells)
            for chunk in candidates:
                for label, category in prefixes.get(chunk["annex"], {}).items():
                    evidence = f"{label.capitalize()} — {source} · Tempo de inaptidão — {target}"
                    if normalized(evidence) in normalized(chunk["text"]):
                        relation = (chunk, source, category, target, "criterio_de_inaptidao",
                                    "TEM_CRITERIO_DE_INAPTIDAO", evidence)
                        if relation not in relations:
                            relations.append(relation)

    results = []
    for chunk, source, source_type, target, target_type, kind, evidence in relations:
        if normalized(evidence) not in normalized(chunk["text"]):
            raise ValueError(f"Evidência ausente em {chunk['id']}.")
        results.append({
            "chunk_id": chunk["id"],
            "entities": [
                {"name": name, "type": category,
                 "canonical_key": f"{category}/{normalized(name)}"}
                for name, category in ((source, source_type), (target, target_type))
            ],
            "relations": [{"source": source, "target": target, "type": kind,
                           "evidence": evidence}],
        })
    destination = folder / "relacoes_piloto_validadas.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)
    print(f"{len(results)} relações do piloto com evidência literal.")


if __name__ == "__main__":
    main()
