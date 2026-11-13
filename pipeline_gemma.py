"""Extração ampliada com evidências literais e cache reproduzível."""
import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from pypdf import PdfReader
from pydantic import BaseModel, ConfigDict, Field
from lm_studio import post, CHAT_MODEL

ROOT = Path(__file__).resolve().parent
COMPACT_PDF = ROOT / "Portaria GM-MS 11685 - versao compacta.pdf"


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)


class Relation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str
    type: str
    evidence: str = Field(min_length=15)


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entities: list[Entity]
    relations: list[Relation]


def normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def relation_type(value):
    decomposed = unicodedata.normalize("NFKD", value.upper())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def chunks(pdf, compact=False):
    reader = PdfReader(pdf)
    result = []
    annex = "corpo"
    internal = ""
    article = None
    current = None
    original = None
    section = ""
    subsection = ""
    table_heading = ""
    table_title = ""
    for page, pdf_page in enumerate(reader.pages, 1):
        lines = pdf_page.extract_text().splitlines()
        for index, raw_line in enumerate(lines):
            line = raw_line.strip()
            if compact and index == 0 and line == str(page):
                continue
            marker = re.fullmatch(r"Página (\d+) do original", line) if compact else None
            if marker:
                original = int(marker[1])
                current = None
                continue
            if not line or re.match(r"^(https://|\d{2}/\d{2}/\d{4},)", line):
                continue
            heading = re.fullmatch(r"ANEXO ([IVXLCDM]+)", line)
            nested = re.match(r"ANEXO (\d+) DO ANEXO (.+)", line)
            provision = re.match(r"Art\.\s*(\d+)[.º°]", line)
            if heading:
                annex, internal, article = heading[1], "", None
            if nested:
                internal, article = nested[1], None
            if heading or nested or (compact and re.match(r"^CAP[IÍ]TULO\b", line, re.I)):
                section = subsection = ""
                table_heading = ""
                table_title = ""
                if compact:
                    article = None
                    current = None
            if compact and re.match(r"^Seção\s+[IVXLCDM]+\b", line, re.I):
                section, subsection, article, current = line, "", None, None
            if compact and re.match(r"^Subseção\s+[IVXLCDM]+\b", line, re.I):
                subsection, article, current = line, None, None
            if provision:
                article = int(provision[1])
            if (current is None or heading or nested or provision
                    or len(current["text"]) + len(line) > 2400):
                scope = annex + (f"/interno-{internal}" if internal else "")
                device = f"art-{article}" if article is not None else "texto"
                current = {"id": f"{scope}/{device}/{len(result)+1:04d}",
                           "annex": annex, "internal_annex": internal,
                           "article": article, "pages": [], "text": ""}
                if compact:
                    current.update(source_pdf=pdf.name, original_pages=[original] if original else [],
                                   section=section, subsection=subsection, incisos=[],
                                   inherited_table_heading=table_heading,
                                   inherited_table_title=table_title)
                result.append(current)
            if compact:
                if line.startswith(("TABELA DE TRIAGEM CLÍNICA", "ESPECIFICAÇÕES DOS COMPONENTES",
                                    "CONTROLE DE QUALIDADE DOS REAGENTES")):
                    table_title, table_heading = line, ""
                elif table_title and (
                    re.match(r"^(?:[A-Z]\s*[-.]\s*)?(?:PRINCIPAIS |CIRURGIAS E PROCEDIMENTOS ODONTOLÓGICOS|"
                             r"ANTI-HIPERTENSIVOS |MEDICAMENTOS |HORMÔNIOS E ANTIMETABÓLICOS)", line)
                    or (index + 1 < len(lines) and lines[index + 1].strip() == "Análises · Valores esperados")
                ):
                    table_heading = line
            inciso = re.match(r"^([IVXLCDM]+)\s*[-–—]\s+", line) if compact and article else None
            if inciso and inciso[1] not in current["incisos"]:
                current["incisos"].append(inciso[1])
            current["text"] += line + "\n"
            if page not in current["pages"]:
                current["pages"].append(page)
    if compact:
        for chunk in result:
            vaccine_rows = re.search(
                r"Vacinas de vírus ou bactérias vivos e atenuados\n"
                r"Vacina · Tempo de inaptidão\n[^\n]+\n"
                r"(?P<blank_rows>.+?)\nOutras vacinas produzidas",
                chunk["text"], re.DOTALL,
            )
            if vaccine_rows:
                chunk["vaccines_with_blank_interval"] = vaccine_rows["blank_rows"].splitlines()
    return result


def compact_units(text):
    """Separa registros e incisos sem quebrar o conteúdo de cada unidade."""
    if text.lstrip().startswith("Medicamento — "):
        return [("", record) for record in re.split(r"\n(?=Medicamento — )", text)]
    parts = re.split(r"\n(?=[IVXLCDM]+\s*[-–—]\s*\S)", text)
    if len(parts) == 1 or not parts[0].lstrip().startswith("Art."):
        return [("", text)]
    return [("", parts[0])] + [(parts[0], item) for item in parts[1:]]


def extract_unit(payload, cache):
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    saved = cache / f"{key}.json"
    response = (json.loads(saved.read_text(encoding="utf-8")) if saved.exists()
                else post("/chat/completions", payload))
    data = Extraction.model_validate_json(response["choices"][0]["message"]["content"])
    if not saved.exists():
        saved.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventario", action="store_true")
    parser.add_argument("--tabelas", action="store_true")
    parser.add_argument("--compacta", action="store_true")
    parser.add_argument("--limite", type=int, help="Máximo de extrações novas nesta execução.")
    parser.add_argument("--trecho", action="append", help="ID de trecho para extrair. Pode ser repetido.")
    parser.add_argument("--revalidar", action="store_true", help="Reaplica a validação aos trechos selecionados, usando o cache quando disponível.")
    args = parser.parse_args()
    if args.compacta and args.tabelas:
        parser.error("A versão compacta já inclui as tabelas em texto.")
    if args.limite is not None and args.limite < 1:
        parser.error("--limite deve ser maior que zero.")
    if args.revalidar and not args.trecho:
        parser.error("--revalidar requer pelo menos um --trecho.")
    output = ROOT / ("dados/compacta" if args.compacta else
                     "dados/gemma_tabelas" if args.tabelas else "dados/integral")
    cache = output / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    if args.tabelas:
        source = ROOT / "dados/integral/trechos_tabelas.json"
        corpus = json.loads(source.read_text(encoding="utf-8"))
    elif args.compacta:
        corpus = chunks(COMPACT_PDF, compact=True)
    else:
        originals = list(ROOT.glob("Minist*.pdf"))
        if len(originals) != 1:
            parser.error("Esperado um único PDF original com nome iniciado por Minist.")
        corpus = chunks(originals[0])
    (output / "trechos.json").write_text(json.dumps(corpus, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.inventario:
        print(len(corpus), "trechos")
        return
    if args.trecho:
        requested = set(args.trecho)
        missing = requested - {chunk["id"] for chunk in corpus}
        if missing:
            parser.error("Trechos inexistentes: " + ", ".join(sorted(missing)))
        corpus = [chunk for chunk in corpus if chunk["id"] in requested]
    results_path = output / "extracoes.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else []
    successful = {row["chunk_id"] for row in results if "error" not in row}
    failed = {row["chunk_id"] for row in results if "error" in row}
    attempted = 0
    for chunk in corpus:
        if chunk["id"] in successful and not args.revalidar:
            continue
        if args.limite is not None and attempted >= args.limite:
            break
        attempted += 1
        results = [row for row in results if row["chunk_id"] != chunk["id"]]
        payload = {
            "model": CHAT_MODEL, "temperature": 0, "max_tokens": 1536 if args.compacta else 4096,
            "messages": [
                {"role": "system", "content": (
                    "Extraia entidades e relacoes sobre doacao de sangue. Escolha nomes e tipos. "
                    "source e target devem corresponder exatamente a nomes de entities. "
                    "Cada evidence deve ser uma passagem literal continua do texto. "
                    + ("Em tabelas, extraia apenas das linhas_alvo e preserve suas celulas e ressalvas. " if args.tabelas else "")
                    + "Preserve negacoes e excecoes. Nao conclua aptidao global. "
                    "Tipos de relacao em MAIUSCULAS_COM_UNDERSCORES."
                )},
                {"role": "user", "content": chunk["text"]},
            ],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "extracao", "strict": True, "schema": Extraction.model_json_schema()
            }},
        }
        if args.compacta:
            payload["messages"][0]["content"] += (
                " Inclua somente entidades que participam das relações. Seja conciso. "
                "Represente exceções explícitas com relações próprias e cite suas condições."
            )
        if chunk["id"] in failed:
            payload["messages"][0]["content"] += (
                " Priorize as seis relações principais e use evidências curtas e literais."
            )
        try:
            units = compact_units(chunk["text"]) if args.compacta else [("", chunk["text"])]
            if len(units) > 1:
                payload["max_tokens"] = 512
                payload["messages"][0]["content"] += (
                    " Extraia apenas da unidade alvo. Use o enunciado para interpretar "
                    "o inciso."
                )
            entities = {}
            accepted = []
            rejected = []
            for context, passage in units:
                payload["messages"][1]["content"] = (
                    f"Enunciado:\n{context}\nUnidade alvo:\n{passage}" if context else passage
                )
                data = extract_unit(payload, cache)
                names = {entity.name for entity in data.entities}
                for entity in data.entities:
                    entities.setdefault(entity.name, entity)
                for relation in data.relations:
                    canonical_type = relation_type(relation.type)
                    valid = (relation.source in names and relation.target in names
                             and normalized(relation.evidence) in normalized(passage)
                             and re.fullmatch(r"[A-Z][A-Z_]{1,63}", canonical_type))
                    row = relation.model_dump()
                    if valid:
                        row["type"] = canonical_type
                        if row not in accepted:
                            accepted.append(row)
                    else:
                        rejected.append(row)
            results.append({"chunk_id": chunk["id"], "entities": [
                {**entity.model_dump(), "canonical_key": normalized(entity.type) + "/" + normalized(entity.name)}
                for entity in entities.values()
            ], "relations": accepted, "rejected": rejected,
                "status": "validado_estruturalmente_revisao_semantica_pendente"})
            print(chunk["id"], len(accepted), "relacoes aceitas", flush=True)
        except Exception as error:
            results.append({"chunk_id": chunk["id"], "error": str(error)})
            print(chunk["id"], "falha registrada", flush=True)
        temporary = results_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(results_path)


if __name__ == "__main__":
    main()
