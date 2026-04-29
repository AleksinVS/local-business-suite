import os
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from .config import load_runtime_settings
from .graph import run_agent, stream_agent
from .mcp_server import build_mcp_server
from .schemas import ChatRequest, ChatResponse


mcp_server = build_mcp_server()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(title="Корпоративный портал ВОБ №3 Agent Runtime", lifespan=lifespan)
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


@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    logger = logging.getLogger(__name__)
    
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")

    async def event_generator():
        try:
            for chunk in stream_agent(
                actor=payload.actor.model_dump(),
                session_id=payload.session_id,
                prompt=payload.prompt,
                history=payload.history,
            ):
                yield f"data: {json.dumps({'content': chunk})}\n\n"
            
            yield "data: [DONE]\n\n"
        except Exception as exc:
            logger.error(f"Error in stream_agent: {exc}", exc_info=True)
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    logger = logging.getLogger(__name__)
    logger.info(
        f"Received chat request: session_id={payload.session_id}, prompt={payload.prompt[:100]}"
    )
    logger.info(f"Actor: {payload.actor}")

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
        logger.error(f"Error in run_agent: {exc}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChatResponse(
        session_id=payload.session_id,
        assistant_message=result["assistant_message"],
        tool_trace=result["tool_trace"],
    )
