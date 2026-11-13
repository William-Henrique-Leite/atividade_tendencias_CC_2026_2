"""Comparação entre busca vetorial e recuperação com grafo."""
import html
import json
import os
import re
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from neo4j import GraphDatabase, READ_ACCESS

from lm_studio import chat, embeddings, stream_chat

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

VECTOR_QUERY = """
CALL db.index.vector.queryNodes('trecho_vetor', 5, $vector)
YIELD node, score
RETURN node.id AS id, node.text AS text, node.pages AS pages,
       node.original_pages AS original_pages, node.section AS section,
       node.internal_annex AS internal_annex, node.incisos AS incisos,
       node.inherited_table_heading AS titulo_da_tabela_continuada,
       node.inherited_table_title AS nome_da_tabela,
       node.vaccines_with_blank_interval AS vacinas_sem_prazo_na_linha,
       node.annex AS annex, node.article AS article, score
ORDER BY score DESC, id
"""

TEXT_QUERY = """
CALL db.index.fulltext.queryNodes('trecho_texto', $terms, {limit: 5})
YIELD node, score
RETURN node.id AS id, node.text AS text, node.pages AS pages,
       node.original_pages AS original_pages, node.section AS section,
       node.internal_annex AS internal_annex, node.incisos AS incisos,
       node.inherited_table_heading AS titulo_da_tabela_continuada,
       node.inherited_table_title AS nome_da_tabela,
       node.vaccines_with_blank_interval AS vacinas_sem_prazo_na_linha,
       node.annex AS annex, node.article AS article
ORDER BY score DESC, id
"""

COMMON_SEARCH_WORDS = {
    "agora", "depois", "doação", "doacao", "doador", "doadora", "meses",
    "posso", "preciso", "quando", "quanto", "sangue", "semana", "semanas",
    "tempo", "tenho",
}

GRAPH_QUERY = """
UNWIND $ids AS id
MATCH (t:TrechoIntegral {id:id})
CALL (t) {
    OPTIONAL MATCH (t)<-[:TEM_EVIDENCIA]-(seed:EntidadeCandidata)
    OPTIONAL MATCH path = (seed)-[:RELACAO_CANDIDATA*1..2]-(neighbor:EntidadeCandidata)
    WHERE any(edge IN relationships(path) WHERE edge.trecho = t.id)
    WITH DISTINCT [edge IN relationships(path) | {
        origem: startNode(edge).name, tipo: edge.tipo, destino: endNode(edge).name,
        evidencia: edge.evidencia, trecho: edge.trecho
    }] AS caminho
    WHERE caminho IS NOT NULL
    ORDER BY size(caminho), [edge IN caminho | edge.trecho]
    LIMIT 8
    RETURN collect(caminho) AS caminhos
}
OPTIONAL MATCH (t)-[:PERTENCE_A]->(scope:EscopoDocumental)
RETURN t.id AS id, t.text AS text, t.pages AS pages, t.annex AS annex,
       t.original_pages AS original_pages, t.section AS section, t.article AS article,
       t.inherited_table_heading AS titulo_da_tabela_continuada,
       t.inherited_table_title AS nome_da_tabela,
       t.vaccines_with_blank_interval AS vacinas_sem_prazo_na_linha,
       scope.id AS escopo_documental, caminhos
"""


def search_terms(question):
    words = re.findall(r"[^\W\d_]{5,}", question.casefold())
    aliases = {"gripado": "gripe", "gripada": "gripe", "gripados": "gripe", "gripadas": "gripe"}
    generic = COMMON_SEARCH_WORDS | {"fiquei", "passada", "passado", "conseguir"}
    return list(dict.fromkeys(aliases.get(word, word) for word in words if word not in generic))


def fuse_rankings(vector_hits, text_hits, k=60):
    fused = {}
    for ranking in (vector_hits, text_hits):
        for rank, item in enumerate(ranking, start=1):
            row = fused.setdefault(item["id"], {**item, "rrf_score": 0.0})
            row["rrf_score"] += 1 / (k + rank)
    return sorted(fused.values(), key=lambda row: (-row["rrf_score"], row["id"]))


def ask_model(question, records, mode):
    if re.search(r"\bvacin\w*\b", question, re.IGNORECASE) and not re.search(
        r"\b(?:e|ou|também)\b", question, re.IGNORECASE
    ):
        for record in records:
            for vaccine in record.get("vacinas_sem_prazo_na_linha") or []:
                if re.search(rf"\b{re.escape(vaccine.rstrip('*'))}\b", question, re.IGNORECASE):
                    return (
                        f"A tabela lista **{vaccine.rstrip('*')}**, com a célula de prazo vazia. "
                        f"O trecho **{record['id']}** não estabelece um prazo específico para "
                        "essa vacina. A aptidão final é avaliada pelo hemocentro."
                    )
    matched = [row for row in records if row.get("text_match")]
    selected = matched if len(matched) >= 2 else records[:3]
    if not any(row.get("caminhos") for row in selected):
        path_source = next((row for row in records if row.get("caminhos")), None)
        if path_source:
            selected = [*selected, path_source]
    question_terms = set(search_terms(question))
    evidence = []
    for row in selected:
        source = {key: row[key] for key in ("id", "text", "titulo_da_tabela_continuada", "nome_da_tabela")
                  if row.get(key)}
        # Recorte apenas trechos compostos integralmente por linhas independentes.
        table_text = re.sub(
            r"\n[A-Z] [-–] [^\n]+\Z", "", row["text"].strip()
        )
        first_label = re.match(r"([^\n—]+) — ", table_text)
        lines = (re.split(rf"\n(?={re.escape(first_label[0])})", table_text)
                 if first_label else [table_text])
        if len(lines) > 1 and all(
            re.fullmatch(r"[^\n]+ — .+? · Tempo de inaptidão — .+", line, re.DOTALL)
            for line in lines
        ):
            relevant = [
                line for line in lines
                if question_terms.intersection(re.findall(r"[^\W\d_]{5,}", line.casefold()))
            ]
            if relevant:
                source["text"] = "\n".join(relevant)
        if row.get("caminhos"):
            # Reutiliza as arestas entre caminhos sem repetir suas citações.
            edges = {}
            for path in row["caminhos"]:
                for edge in path:
                    key = (edge["origem"], edge["tipo"], edge["destino"], edge["trecho"], edge["evidencia"])
                    edges[key] = edge
            ranked_edges = sorted(edges.values(), key=lambda edge: (
                -len(question_terms.intersection(re.findall(
                    r"[^\W\d_]{5,}", edge["evidencia"].casefold()
                ))), edge["trecho"] != row["id"],
            ))
            source["relacoes"] = ranked_edges[:2]
        evidence.append(source)
    context = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
    return stream_chat([
        {"role": "system", "content": (
            "Você responde perguntas sobre doação de sangue com base exclusivamente "
            "no contexto fornecido. Cite os IDs dos trechos utilizados. Preserve condições, "
            "exceções, datas e unidades. Quando a fonte só cobrir um subtipo ou "
            "uma condição, informe o que ela diz e indique qual informação falta "
            "para aplicar a regra ao caso. Não responda apenas 'não sei' se houver "
            "evidência parcial. O título de tabela continuada vale até o próximo título. "
            "Em tabelas, associe um prazo apenas à linha ou ao grupo que a fonte "
            "vincula explicitamente a ele. Para linha sem prazo, procure uma nota "
            "que mencione o item. Não copie o prazo de uma linha vizinha nem aplique "
            "a itens listados uma nota destinada a itens não listados. "
            "A aptidão final é avaliada pelo hemocentro. Relações candidatas são "
            "extrações não revisadas, sempre confira o texto. Responda em português, "
            "em até três frases, com a regra, as ressalvas e os IDs usados."
            " Se a entrada for apenas um termo e tiver vários sentidos no contexto, "
            "pergunte qual aspecto interessa, sem listar todas as ocorrências."
        )},
        {"role": "user", "content": f"Pergunta: {question}\nMétodo: {mode}\nContexto: {context}"},
    ], max_tokens=512)


def show_answer(answer):
    if isinstance(answer, str):
        st.write(answer)
        return answer
    try:
        with st.spinner("Gerando resposta..."):
            text = "".join(answer)
    except (TimeoutError, OSError, ValueError) as error:
        st.warning(f"O LM Studio interrompeu a geração. Os trechos recuperados estão disponíveis. ({error})")
        return ""
    if not text:
        st.warning("O modelo não retornou uma resposta. Confira os trechos recuperados.")
    else:
        st.write(text)
    return text


def is_relevant(question):
    if re.search(r"\b(?:doar|doaç(?:ão|ões)|doac(?:ao|oes)|doador(?:a|es|as)?|hemoterapia|hemocentro|tatuage(?:m|ns))\b",
                 question, re.IGNORECASE):
        return True
    answer = chat([
        {"role": "system", "content": (
            "Classifique se a pergunta trata de doação de sangue, hemoterapia ou "
            "regras do candidato à doação. Responda somente SIM ou NAO."
        )},
        {"role": "user", "content": question},
    ], max_tokens=24)
    return answer.strip().rstrip(".").upper() not in {"NÃO", "NAO"}


st.set_page_config(page_title="Doação de sangue", page_icon="🩸", layout="wide")
st.title("Orientações para doação de sangue")
st.caption("Consulte os critérios da portaria e as fontes usadas em cada resposta.")
question = st.text_input("Qual é sua dúvida?")
submitted = st.button("Consultar", type="primary")
if submitted and question.strip():
    try:
        if not is_relevant(question):
            st.warning("Essa pergunta não corresponde à finalidade do sistema, que trata de doação de sangue.")
            st.stop()
        with st.spinner("Consultando as fontes..."):
            with GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(
                os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]
            )) as driver:
                database = os.getenv("DOACAO_APP_DATABASE", "doacao-compacta")
                with driver.session(database=database,
                                    default_access_mode=READ_ACCESS) as session:
                    terms = search_terms(question)
                    query_text = " ".join(terms) if re.search(
                        r"\bgripad[oa]s?\b", question, re.IGNORECASE
                    ) else question
                    vector = embeddings([query_text], query=True)[0]
                    retrieved = [row.data() for row in session.run(VECTOR_QUERY, vector=vector)]
                    vector_ranking = retrieved
                    exact = []
                    if database == "doacao-compacta":
                        if terms:
                            exact = [row.data() for row in session.run(
                                TEXT_QUERY, terms=" OR ".join(f'"{term}"' for term in terms)
                            )]
                            vector_hits = {item["id"]: item for item in retrieved}
                            for item in exact:
                                item.update(score=vector_hits.get(item["id"], {}).get("score"),
                                            text_match=True)
                            ordered = {item["id"]: item for item in exact}
                            for item in retrieved:
                                ordered.setdefault(item["id"], item)
                            retrieved = list(ordered.values())[:5]
                    rag_results = fuse_rankings(
                        vector_ranking, exact
                    )[:3]
                    graph = [row.data() for row in session.run(
                        GRAPH_QUERY, ids=[item["id"] for item in retrieved]
                    )] if retrieved else []
                    graph_by_id = {row["id"]: row for row in graph}
                    graph = [
                        {**graph_by_id[item["id"]], "text_match": item.get("text_match", False)}
                        for item in retrieved if item["id"] in graph_by_id
                    ]
        if not retrieved:
            st.warning("Ainda não há trechos indexados disponíveis.")
            st.stop()
        rag_tab, graph_tab = st.tabs(["RAG tradicional", "GraphRAG"])
        with rag_tab:
            method = "Busca híbrida (vetorial + textual)" if exact else "Busca vetorial"
            st.write(f"**Método de recuperação** · {method}")
            st.caption("RRF com k = 60. Cada lista contribui com 1/(60 + posição), começando em 1.")
            st.subheader("Top 3 trechos")
            for rank, item in enumerate(rag_results, start=1):
                label = (
                    f"{rank}. RRF {item['rrf_score']:.5f} · Anexo {item['annex']} "
                    f"· Artigo {item['article'] or '—'} · páginas {item['pages']}"
                )
                with st.expander(label):
                    st.write(item["text"])
                    if item["nome_da_tabela"]:
                        st.caption(item["nome_da_tabela"])
                    if item["titulo_da_tabela_continuada"]:
                        st.caption(item["titulo_da_tabela_continuada"])
                    if item["original_pages"]:
                        st.caption(f"Páginas no PDF original: {item['original_pages']}")
                    if item["section"]:
                        st.caption(item["section"])
                    if item["internal_annex"]:
                        st.caption(f"Anexo interno {item['internal_annex']}")
                    if item["incisos"]:
                        st.caption("Incisos " + ", ".join(item["incisos"]))
                    st.caption(f"ID {item['id']}")
                    if item.get("text_match"):
                        st.caption("Correspondência textual")
            st.subheader("Resposta final")
            rag_answer = show_answer(ask_model(question, rag_results, method))
        with graph_tab:
            paths = list({
                tuple((edge["origem"], edge["tipo"], edge["destino"]) for edge in path)
                for row in graph for path in row["caminhos"] if path
            })
            paths.sort(key=lambda path: (len(path), path))
            entities = sorted({name for path in paths for source, _, target in path
                               for name in (source, target)}, key=str.casefold)
            st.subheader("Entidades encontradas")
            if entities:
                for entity in entities:
                    st.html(
                        '<div style="border:1px solid #0e7490;border-left:4px solid #0e7490;'
                        'border-radius:9px;padding:8px 14px;background:#ecfeff;color:#164e63;'
                        f'font-weight:600;overflow-wrap:anywhere">{html.escape(entity)}</div>'
                    )
            else:
                st.info("Nenhuma entidade encontrada para os trechos recuperados.")

            st.subheader("Caminhos no grafo")
            if paths:
                for path in paths:
                    steps = [f"{source} → {kind} → {target}" for source, kind, target in path]
                    content = "<br>".join(html.escape(step) for step in steps)
                    st.html(
                        '<div style="border:1px solid #7c3aed;border-left:4px solid #7c3aed;'
                        'border-radius:9px;padding:10px 14px;background:#f5f3ff;color:#4c1d95;'
                        f'font-family:monospace;overflow-wrap:anywhere">{content}</div>'
                    )
            else:
                st.info("Nenhum caminho encontrado para os trechos recuperados.")

            st.subheader("Resposta final")
            same_sources = {row["id"] for row in graph} == {row["id"] for row in rag_results}
            if not paths and same_sources and rag_answer:
                st.write(rag_answer)
            else:
                show_answer(ask_model(question, graph, "grafo e trechos"))
    except Exception as error:
        st.error(f"Não foi possível completar a consulta. Verifique o Neo4j e o LM Studio. Detalhe: {html.escape(str(error))}")
