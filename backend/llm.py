"""LLM / Embedding / Vision clients — OpenAI-compatible (百炼 DashScope by default).

All functions degrade to deterministic mocks when MOCK_LLM=1 or no API key,
so the whole suite is demoable/testable without any model access.
"""
import base64
import json
import re

import httpx

import config


def _headers(key=None):
    return {"Authorization": "Bearer " + (key or config.AI_API_KEY),
            "Content-Type": "application/json"}


def chat(messages, model=None, temperature=0.2, max_tokens=2000, timeout=None):
    """OpenAI-compatible chat completion. Returns text ("" on failure with mock off)."""
    if config.MOCK_LLM:
        return _mock_chat(messages)
    payload = {"model": model or config.AI_MODEL, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    try:
        r = httpx.post(config.AI_API_BASE + "/chat/completions", json=payload,
                       headers=_headers(), timeout=timeout or config.AI_TIMEOUT)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:  # noqa
        return "[LLM_ERROR] %s" % e


def chat_json(messages, model=None, temperature=0.1, max_tokens=1500):
    """Chat expecting a JSON object; tolerant extraction."""
    txt = chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)
    return parse_json_block(txt), txt


def parse_json_block(txt):
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", txt, re.S)
    cand = m.group(1) if m else None
    if not cand:
        m2 = re.search(r"\{.*\}", txt, re.S)
        cand = m2.group(0) if m2 else None
    if not cand:
        return {}
    try:
        return json.loads(cand)
    except Exception:  # noqa
        return {}


def embed(texts):
    """Embedding via OpenAI-compatible endpoint. Returns list[list[float]] (mock: hashed pseudo-vectors)."""
    if config.MOCK_LLM:
        return [_mock_vector(t) for t in texts]
    try:
        r = httpx.post(config.AI_API_BASE + "/embeddings",
                       json={"model": config.AI_EMBED_MODEL, "input": texts},
                       headers=_headers(), timeout=120)
        r.raise_for_status()
        data = r.json()["data"]
        data.sort(key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]
    except Exception:  # noqa
        return [_mock_vector(t) for t in texts]


def vision_caption(image_b64, prompt, model=None):
    """Caption an image (base64, no data: prefix) with a VL model."""
    if config.MOCK_LLM:
        return "[mock] 画面描述：演示用关键帧描述（未配置视觉模型）。"
    messages = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_b64}},
        {"type": "text", "text": prompt},
    ]}]
    payload = {"model": model or config.VL_MODEL, "messages": messages, "max_tokens": 500}
    try:
        r = httpx.post(config.AI_API_BASE + "/chat/completions", json=payload,
                       headers=_headers(), timeout=180)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:  # noqa
        return "[VL_ERROR] %s" % e


def transcribe_audio_wav(wav_bytes, filename="audio.wav"):
    """ASR adapter A: OpenAI-compatible /audio/transcriptions (Groq/SiliconFlow/…)."""
    if not config.ASR_API_BASE or not config.ASR_API_KEY:
        return None
    try:
        r = httpx.post(config.ASR_API_BASE.rstrip("/") + "/audio/transcriptions",
                       files={"file": (filename, wav_bytes, "audio/wav")},
                       data={"model": config.ASR_MODEL},
                       headers={"Authorization": "Bearer " + config.ASR_API_KEY},
                       timeout=600)
        r.raise_for_status()
        return r.json().get("text", "")
    except Exception:  # noqa
        return None


def transcribe_audio_omni(wav_b64, model=None):
    """ASR adapter B: chat-completions with input_audio (百炼 qwen-omni 系)。"""
    m = model or config.ASR_OMNI_MODEL
    if not m or config.MOCK_LLM:
        return None
    messages = [{"role": "user", "content": [
        {"type": "input_audio", "input_audio": {"data": "data:;base64," + wav_b64, "format": "wav"}},
        {"type": "text", "text": "请把这段音频逐句转写为中文文本，保留时间顺序，不要总结。"},
    ]}]
    payload = {"model": m, "messages": messages, "max_tokens": 4000,
               "modalities": ["text"], "stream": False}
    try:
        r = httpx.post(config.AI_API_BASE + "/chat/completions", json=payload,
                       headers=_headers(), timeout=600)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:  # noqa
        return None


# ---------------- mocks ----------------
def _mock_chat(messages):
    last = messages[-1]["content"] if messages else ""
    if isinstance(last, list):
        last = str(last)
    if "faithfulness" in last or "忠实度" in last:
        return json.dumps({"faithfulness": 0.9, "answer_relevancy": 0.85,
                           "context_precision": 0.8, "context_recall": 0.75,
                           "reason": "mock judge"}, ensure_ascii=False)
    return "这是 MOCK 模式返回的示例回答（未配置 AI_API_KEY）。"


def _mock_vector(text, dim=64):
    """Deterministic pseudo-embedding from char codes — same text ⇒ same vector,
    similar texts share prefixes so cosine similarity still behaves sanely for demos."""
    import hashlib
    h = hashlib.sha256(text.encode("utf-8")).digest()
    base = [b / 255.0 for b in h] * (dim // 32 + 1)
    vec = base[:dim]
    # blend in a bag-of-chars component so similar texts get similar vectors
    bag = [0.0] * dim
    for ch in text[:400]:
        bag[ord(ch) % dim] += 1.0
    n = sum(bag) or 1.0
    return [0.5 * vec[i] + 0.5 * bag[i] / n * 10 for i in range(dim)]


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
