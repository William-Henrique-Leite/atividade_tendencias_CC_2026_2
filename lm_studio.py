"""Cliente local do LM Studio para extração, geração e embeddings."""
import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE_URL = "http://127.0.0.1:1234/v1"
CHAT_MODEL = os.getenv("LM_STUDIO_CHAT_MODEL", "gemma-4-e4b-it")
EMBEDDING_MODEL = "text-embedding-nomic-embed-text-v1.5"


def post(endpoint, payload):
    request = Request(
        BASE_URL + endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=180) as response:
            return json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LM Studio HTTP {error.code}: {detail}") from error


def chat(messages, *, max_tokens=2048):
    result = post("/chat/completions", {
        "model": CHAT_MODEL,
        "messages": messages,
        "temperature": 0,
        "max_tokens": max_tokens,
    })
    return result["choices"][0]["message"]["content"]


def stream_chat(messages, *, max_tokens):
    request = Request(
        BASE_URL + "/chat/completions",
        data=json.dumps({
            "model": CHAT_MODEL, "messages": messages, "temperature": 0,
            "max_tokens": max_tokens, "stream": True,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=120) as response:
        for line in response:
            if not line.startswith(b"data:"):
                continue
            event = line[5:].strip()
            if event == b"[DONE]":
                break
            choices = json.loads(event).get("choices") or []
            if choices and choices[0].get("finish_reason") == "length":
                raise ValueError("A resposta atingiu o limite de tokens.")
            if choices and (content := choices[0].get("delta", {}).get("content")):
                yield content


def embeddings(texts, query=False):
    prefix = "search_query: " if query else "search_document: "
    result = post("/embeddings", {
        "model": EMBEDDING_MODEL,
        "input": [prefix + text for text in texts],
    })
    rows = sorted(result["data"], key=lambda row: row["index"])
    if len(rows) != len(texts):
        raise ValueError("Quantidade de embeddings diferente da quantidade de textos.")
    return [row["embedding"] for row in rows]
