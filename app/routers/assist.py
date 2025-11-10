from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

# Use the same dependency as your other routers
from app.deps.auth import require_auth
from app.services.openai_client import chat_once, stream_chat
from app.services.embeddings import search_embeddings

router = APIRouter(prefix="/assist", tags=["assist"])


class Message(BaseModel):
    role: str = Field(..., pattern="^(system|user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]
    system: Optional[str] = None
    model: Optional[str] = None
    stream: bool = False
    extra: Optional[Dict[str, Any]] = None  # forwarded to Responses API


@router.post("/chat", dependencies=[Depends(require_auth)])
async def chat(req: ChatRequest):
    # keep only user/assistant messages; system is passed separately
    msgs = [m.model_dump()
            for m in req.messages if m.role in ("user", "assistant")]

    if req.stream:
        async def generator():
            async for token in stream_chat(
                messages=msgs,
                system=req.system,
                model=req.model,
                extra=req.extra
            ):
                yield token
        return StreamingResponse(generator(), media_type="text/plain")
    else:
        data = await chat_once(
            messages=msgs,
            system=req.system,
            model=req.model,
            extra=req.extra
        )
        return JSONResponse({"text": data["text"], "model": data["model"], "raw": data["raw"]})


@router.get("/search", dependencies=[Depends(require_auth)])
async def assist_search(q: str, k: int = 8, entity_type: str | None = None, scope_id: str | None = None):
    """Vector search over embeddings store. Returns top-k matches with context."""
    matches = search_embeddings(
        q=q, k=k, entity_type=entity_type, scope_id=scope_id)
    return {
        "q": q,
        "k": k,
        "entity_type": entity_type,
        "scope_id": scope_id,
        "results": [
            {
                "id": m.id,
                "entity_type": m.entity_type,
                "entity_id": m.entity_id,
                "scope_id": m.scope_id,
                "title": m.title,
                "text": m.text,
                "score": m.score,
                "meta": m.meta,
            }
            for m in matches
        ],
    }
