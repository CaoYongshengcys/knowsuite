"""Minimal RAGFlow REST client (v1 API) with full mock fallback.

Docs: https://ragflow.io/docs/dev/http_api_reference
All methods return plain dicts/lists; in mock mode they return deterministic
canned data so every KnowSuite module stays demoable without a RAGFlow instance.
"""
import hashlib

import httpx

import config

TIMEOUT = 60


def _h():
    return {"Authorization": "Bearer " + config.RAGFLOW_API_KEY}


def _base():
    return config.RAGFLOW_API_BASE + "/api/v1"


def mocked():
    return config.MOCK_RAGFLOW


def _get(path, params=None):
    r = httpx.get(_base() + path, headers=_h(), params=params or {}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _post(path, json=None, files=None, data=None):
    if files is not None:
        r = httpx.post(_base() + path, headers=_h(), files=files, data=data or {}, timeout=600)
    else:
        r = httpx.post(_base() + path, headers=_h(), json=json or {}, timeout=300)
    r.raise_for_status()
    return r.json()


def _delete(path, json=None):
    r = httpx.request("DELETE", _base() + path, headers=_h(), json=json or {}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ---------------- datasets ----------------
def list_datasets(page=1, size=50):
    if mocked():
        return [{"id": "mock-kb-1", "name": "演示知识库", "document_count": 3,
                 "chunk_count": 120, "embedding_model": "text-embedding-v4"}]
    d = _get("/datasets", {"page": page, "page_size": size})
    return d.get("data") or []


def create_dataset(name, **kw):
    if mocked():
        return {"id": "mock-kb-" + hashlib.md5(name.encode()).hexdigest()[:8], "name": name}
    d = _post("/datasets", {"name": name, **kw})
    return d.get("data") or {}


# ---------------- documents ----------------
def list_documents(kb_id, page=1, size=100, keywords=""):
    if mocked():
        return [{"id": "mock-doc-1", "name": "示例论文v2.pdf", "run": "DONE",
                 "chunk_count": 42, "size": 1048576}]
    d = _get("/datasets/%s/documents" % kb_id,
             {"page": page, "page_size": size, "keywords": keywords})
    return (d.get("data") or {}).get("docs") or []


def upload_documents(kb_id, files):
    """files: list of (filename, bytes)."""
    if mocked():
        out = []
        for fn, _ in files:
            out.append({"id": "mock-doc-" + hashlib.md5(fn.encode()).hexdigest()[:10], "name": fn})
        return out
    multipart = [("file", (fn, data)) for fn, data in files]
    d = _post("/datasets/%s/documents" % kb_id, files=multipart)
    return d.get("data") or []


def parse_documents(kb_id, doc_ids):
    if mocked():
        return {"ok": True, "mock": True}
    return _post("/datasets/%s/chunks" % kb_id, {"document_ids": doc_ids})


def delete_documents(kb_id, doc_ids):
    if mocked():
        return {"ok": True, "mock": True}
    return _delete("/datasets/%s/documents" % kb_id, {"ids": doc_ids})


def get_document_text(kb_id, doc_id, max_chunks=200):
    """Fetch chunk contents to reconstruct an approximate document text."""
    if mocked():
        return "这是 MOCK 模式的文档正文示例。第一段内容……\n第二段内容……"
    texts = []
    page = 1
    while page <= 5:
        d = _get("/datasets/%s/chunks" % kb_id, {"document_id": doc_id, "page": page, "page_size": 64})
        chunks = (d.get("data") or {}).get("chunks") or []
        if not chunks:
            break
        texts.extend(c.get("content", "") for c in chunks)
        page += 1
        if len(chunks) < 64 or page > max_chunks // 64 + 2:
            break
    return "\n".join(texts)


# ---------------- retrieval / chat ----------------
def retrieval(question, kb_ids, top_k=8, similarity_threshold=0.2):
    if mocked():
        return [{"content": "MOCK 检索片段 %d：与「%s」相关的知识库内容。" % (i + 1, question[:20]),
                 "document_name": "示例论文v2.pdf", "score": 0.9 - i * 0.05}
                for i in range(3)]
    d = _post("/retrieval", {"question": question, "dataset_ids": kb_ids,
                             "top_k": top_k, "similarity_threshold": similarity_threshold,
                             "page_size": top_k})
    return (d.get("data") or {}).get("chunks") or []


def chat_completion(chat_id, question, session_id=None):
    """Use a RAGFlow chat assistant (OpenAI-compatible endpoint)."""
    if mocked():
        return "MOCK 回答：根据知识库，「%s」的要点包括 A、B、C。" % question[:30], ["mock 引用片段"]
    url = config.RAGFLOW_API_BASE + "/api/v1/chats_openai/%s/chat/completions" % chat_id
    payload = {"model": chat_id,
               "messages": [{"role": "user", "content": question}],
               "stream": False}
    if session_id:
        payload["user"] = session_id
    r = httpx.post(url, headers=_h(), json=payload, timeout=300)
    r.raise_for_status()
    data = r.json()
    answer = data["choices"][0]["message"]["content"]
    contexts = []
    refs = (data.get("choices")[0].get("message") or {}).get("references") or data.get("references") or []
    if isinstance(refs, dict):
        refs = refs.get("chunks") or []
    for c in refs:
        if isinstance(c, dict):
            contexts.append(c.get("content", ""))
    return answer, contexts
