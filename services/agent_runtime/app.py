import os
import json
import logging
import hashlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from .config import load_runtime_settings, get_available_models
from .graph import run_agent, stream_agent
from .mcp_server import build_mcp_server
from .schemas import ChatRequest, ChatResponse


mcp_server = build_mcp_server()


def _prompt_hash(prompt: str) -> str:
    if not prompt:
        return ""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _safe_chat_log_context(payload: ChatRequest, actor_context) -> dict:
    return {
        "session_id": payload.session_id,
        "conversation_id": actor_context.conversation_id,
        "request_id": actor_context.request_id,
        "origin_channel": actor_context.origin_channel,
        "model_id": payload.model_id,
        "prompt_sha256": _prompt_hash(payload.prompt),
        "prompt_length": len(payload.prompt or ""),
        "history_count": len(payload.history or []),
        "actor_user_id": actor_context.user_id,
        "actor_channel": actor_context.channel,
        "actor_source": actor_context.source,
        "actor_is_superuser": actor_context.is_superuser,
        "actor_roles_count": len(actor_context.roles or []),
        "page_context_present": bool(actor_context.page_context),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(title="Корпоративный портал ВОБ №3 Agent Runtime", lifespan=lifespan)
app.mount("/mcp", mcp_server.streamable_http_app())


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/details")
def health_details():
    settings = load_runtime_settings()
    return {"status": "ok", "model": settings.model}


@app.get("/models")
def list_models():
    return {"models": get_available_models()}


@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    logger = logging.getLogger(__name__)
    actor_context = payload.actor.ensure_trace_context()
    log_context = _safe_chat_log_context(payload, actor_context)
    logger.info("Agent runtime stream request: %s", log_context)
    
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")

    async def event_generator():
        try:
            for chunk in stream_agent(
                actor=actor_context.model_dump(),
                session_id=payload.session_id,
                prompt=payload.prompt,
                history=payload.history,
                conversation_id=actor_context.conversation_id,
                request_id=actor_context.request_id,
                origin_channel=actor_context.origin_channel,
                actor_version=actor_context.actor_version,
                model_id=payload.model_id,
            ):
                if isinstance(chunk, dict):
                    yield f"data: {json.dumps(chunk)}\n\n"
                else:
                    yield f"data: {json.dumps({'content': chunk})}\n\n"
            
            yield "data: [DONE]\n\n"
        except Exception as exc:
            logger.error(
                "Agent runtime stream failed: request_id=%s conversation_id=%s error_type=%s",
                actor_context.request_id,
                actor_context.conversation_id,
                exc.__class__.__name__,
            )
            yield "data: " + json.dumps(
                {
                    "error": "agent_runtime_error",
                    "request_id": actor_context.request_id,
                    "conversation_id": actor_context.conversation_id,
                }
            ) + "\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    logger = logging.getLogger(__name__)
    actor_context = payload.actor.ensure_trace_context()
    log_context = _safe_chat_log_context(payload, actor_context)
    logger.info("Agent runtime chat request: %s", log_context)

    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")
    try:
        result = run_agent(
            actor=actor_context.model_dump(),
            session_id=payload.session_id,
            prompt=payload.prompt,
            history=payload.history,
            conversation_id=actor_context.conversation_id,
            request_id=actor_context.request_id,
            origin_channel=actor_context.origin_channel,
            actor_version=actor_context.actor_version,
            model_id=payload.model_id,
        )
    except Exception as exc:
        logger.error(
            "Agent runtime chat failed: request_id=%s conversation_id=%s error_type=%s",
            actor_context.request_id,
            actor_context.conversation_id,
            exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "agent_runtime_error",
                "request_id": actor_context.request_id,
                "conversation_id": actor_context.conversation_id,
            },
        ) from exc
    return ChatResponse(
        session_id=payload.session_id,
        assistant_message=result["assistant_message"],
        tool_trace=result["tool_trace"],
        ui_commands=result.get("ui_commands", []),
        conversation_id=actor_context.conversation_id,
        request_id=actor_context.request_id,
    )
