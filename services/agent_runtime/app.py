import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from .config import load_runtime_settings
from .graph import run_agent
from .mcp_server import build_mcp_server
from .schemas import ChatRequest, ChatResponse


mcp_server = build_mcp_server()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(title="Local Business Suite Agent Runtime", lifespan=lifespan)
app.mount("/mcp", mcp_server.streamable_http_app())


@app.get("/health")
def health():
    settings = load_runtime_settings()
    return {
        "status": "ok",
        "model": settings.model,
        "gateway_url": settings.django_gateway_url,
        "openai_key_configured": bool(os.environ.get("OPENAI_API_KEY")),
    }


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")
    try:
        result = run_agent(
            actor=payload.actor.model_dump(),
            session_id=payload.session_id,
            prompt=payload.prompt,
            history=payload.history,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChatResponse(
        session_id=payload.session_id,
        assistant_message=result["assistant_message"],
        tool_trace=result["tool_trace"],
    )
