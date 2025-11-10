# app/services/openai_client.py
from typing import AsyncGenerator, Dict, List, Optional, Any
import asyncio
try:
    from openai import AsyncOpenAI, OpenAI  # type: ignore
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore
    OpenAI = None  # type: ignore
from app.settings import settings
from .usage_log import record_quota_event
import hashlib

# Single client for app lifetime (typed as Any for compatibility in dev without openai)
_client: Any | None = None


def get_client() -> Any:
    global _client
    if _client is None:
        if AsyncOpenAI is None:
            raise RuntimeError("openai package not available")
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _to_responses_input(messages: List[Dict[str, str]], system: Optional[str]) -> List[Dict[str, str]]:
    """
    Convert simple chat messages to Responses API input.
    Each item: {"role": "system"|"user"|"assistant", "content": "text"}
    """
    items: List[Dict[str, str]] = []
    if system:
        items.append({"role": "system", "content": system})
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        items.append({"role": role, "content": content})
    return items


async def chat_once(
    messages: List[Dict[str, str]],
    system: Optional[str] = None,
    model: Optional[str] = None,
    extra: Optional[Dict] = None
) -> Dict:
    """
    Non-streaming chat call using the Responses API.
    Returns {"model": str, "text": str, "raw": dict}
    """
    client = get_client()
    _model = model or settings.OPENAI_MODEL
    payload = {
        "model": _model,
        "input": _to_responses_input(messages, system),
    }
    if extra:
        payload.update(extra)

    resp = await client.responses.create(**payload)

    # Record quota usage if available (best effort)
    usage = getattr(resp, "usage", None)
    try:
        if usage is not None and hasattr(usage, "to_dict"):
            usage_dict = usage.to_dict()  # type: ignore[call-arg]
        elif isinstance(usage, dict):
            usage_dict = usage
        else:
            usage_dict = {}
    except Exception:
        usage_dict = {}
    if not usage_dict and hasattr(resp, "to_dict"):
        try:
            usage_dict = resp.to_dict().get("usage", {})
        except Exception:
            usage_dict = {}
    # Record tokens and a request count
    try:
        if isinstance(usage_dict, dict):
            it = int(usage_dict.get("input_tokens") or 0)
            ot = int(usage_dict.get("output_tokens") or 0)
            if it:
                record_quota_event("openai", "input_tokens", it,
                                   endpoint="responses.create", extra={"model": _model})
            if ot:
                record_quota_event("openai", "output_tokens", ot,
                                   endpoint="responses.create", extra={"model": _model})
        record_quota_event("openai", "requests", 1,
                           endpoint="responses.create", extra={"model": _model})
    except Exception:
        pass

    # Extract primary text
    text_chunks: List[str] = []
    # The SDK returns a structured Output; iterate defensively
    for item in getattr(resp, "output", []) or []:
        if getattr(item, "type", "") == "message":
            for content in getattr(item, "content", []) or []:
                if getattr(content, "type", "") == "output_text":
                    text_chunks.append(getattr(content, "text", ""))
    return {
        "model": _model,
        "text": "".join(text_chunks),
        "raw": resp.to_dict() if hasattr(resp, "to_dict") else resp,  # tolerate sdk changes
    }


async def stream_chat(
    messages: List[Dict[str, str]],
    system: Optional[str] = None,
    model: Optional[str] = None,
    extra: Optional[Dict] = None
) -> AsyncGenerator[str, None]:
    """
    Streaming chat generator yielding text deltas.
    """
    client = get_client()
    _model = model or settings.OPENAI_MODEL
    payload = {
        "model": _model,
        "input": _to_responses_input(messages, system),
        "stream": True,
    }
    if extra:
        payload.update(extra)

    # Stream with event types per Responses API
    # Record request count for streaming
    try:
        record_quota_event("openai", "requests", 1,
                           endpoint="responses.stream", extra={"model": _model})
    except Exception:
        pass

    async with client.responses.stream(**payload) as stream:
        async for event in stream:
            et = getattr(event, "type", "")
            if et == "response.output_text.delta":
                yield getattr(event, "delta", "")
            elif et == "response.completed":
                break
            elif et == "error":
                # surface an error marker then exit
                yield f"\n[error] {getattr(event, 'message', 'unknown error')}"
                break

    await asyncio.sleep(0)


# ---------- Embeddings (synchronous) ----------

def embed_texts(texts: List[str], model: Optional[str] = None) -> Dict[str, Any]:
    """Generate embeddings for a list of texts.

    Returns { model, data:[{index, embedding, text}], usage:{prompt_tokens} }
    Records approximate input token usage to quota tracking.
    """
    model = model or settings.OPENAI_EMBEDDING_MODEL if hasattr(
        settings, 'OPENAI_EMBEDDING_MODEL') else 'text-embedding-3-small'
    if not texts:
        return {"model": model, "data": [], "usage": {}}
    if OpenAI is None or not getattr(settings, 'OPENAI_API_KEY', None):
        # Dev fallback: zero vectors
        dim = 1536
        return {"model": model, "data": [{"index": i, "embedding": [0.0]*dim, "text": t} for i, t in enumerate(texts)], "usage": {}}
    client = OpenAI(api_key=getattr(
        settings, 'OPENAI_API_KEY', None))  # type: ignore
    resp = client.embeddings.create(model=model, input=texts)  # type: ignore
    prompt_tokens = getattr(resp, 'usage', {}).get(
        'prompt_tokens', sum(len(t.split()) for t in texts))
    try:
        record_quota_event('openai', 'input_tokens', int(
            prompt_tokens or 0), endpoint='embeddings.create', extra={'model': model})
        record_quota_event('openai', 'requests', 1,
                           endpoint='embeddings.create', extra={'model': model})
    except Exception:
        pass
    data_out = []
    for i, item in enumerate(getattr(resp, 'data', [])):
        emb = getattr(item, 'embedding', [])
        data_out.append({"index": i, "embedding": emb, "text": texts[i]})
    return {"model": model, "data": data_out, "usage": {"prompt_tokens": prompt_tokens}}


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
