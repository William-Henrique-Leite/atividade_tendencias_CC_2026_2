"""Extract the initial donation criteria with PDF page provenance."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader

ARTICLES = (36, 38, 39, 40)
DOCUMENT_ID = "portaria-11685-2026"
SOURCE_URL = "https://bvsms.saude.gov.br/bvs/saudelegis/gm/2026/prt11685_03_07_2026.html"
ARTICLE = re.compile(r"^Art\.\s+(\d+)\.")
PARAGRAPH = re.compile(r"^\u00a7\s*(\d+)\s*[\u00ba\u00b0]")
PRINT_METADATA = re.compile(r"^(?:\d{2}/\d{2}/\d{4},\s+\d{2}:\d{2}\b|https://bvsms\.saude\.gov\.br/.*\s+\d+/\d+$)")


def extract(pdf: Path) -> dict:
    reader = PdfReader(pdf)
    if len(reader.pages) < 8 or "11.685" not in reader.pages[0].extract_text():
        raise ValueError("Esperado o PDF da Portaria GM/MS 11.685/2026 usado no projeto.")

    sections = {}
    article = None
    paragraph = None
    for page_number in (7, 8):
        page_text = reader.pages[page_number - 1].extract_text()
        if not page_text.strip():
            raise ValueError(f"Pagina {page_number} sem texto extraivel.")
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if not line or PRINT_METADATA.match(line):
                continue
            article_match = ARTICLE.match(line)
            paragraph_match = PARAGRAPH.match(line)
            if article_match:
                article = int(article_match[1])
                paragraph = None
            elif paragraph_match:
                paragraph = int(paragraph_match[1])
            if article not in ARTICLES:
                continue
            key = (article, paragraph)
            entry = sections.setdefault(key, {"pages": set(), "lines": []})
            entry["pages"].add(page_number)
            entry["lines"].append(line)

    expected = {(number, None) for number in ARTICLES}
    expected.update(
        (number, paragraph)
        for number, count in ((36, 2), (38, 2), (39, 5), (40, 2))
        for paragraph in range(1, count + 1)
    )
    if sections.keys() != expected:
        raise ValueError("O recorte do PDF nao corresponde aos artigos e paragrafos esperados.")

    chunks = []
    for (number, paragraph), entry in sections.items():
        article_id = f"{DOCUMENT_ID}/iv-b/art-{number}"
        suffix = "caput" if paragraph is None else f"par-{paragraph}"
        chunks.append({
            "id": f"{article_id}/{suffix}",
            "article_id": article_id,
            "section": "IV-B",
            "article": number,
            "paragraph": paragraph,
            "pages": sorted(entry["pages"]),
            "text": " ".join(entry["lines"]),
        })
    return {
        "document": {
            "id": DOCUMENT_ID,
            "filename": pdf.name,
            "source_url": SOURCE_URL,
            "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "page_count": len(reader.pages),
        },
        "chunks": chunks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dados/trechos.json"))
    args = parser.parse_args()
    result = extract(args.pdf)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{len(result['chunks'])} trechos salvos em {args.output}")


if __name__ == "__main__":
    main()
