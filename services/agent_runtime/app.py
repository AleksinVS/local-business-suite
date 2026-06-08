import os
import json
import logging
import hashlib
import hmac
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from .ag_ui_adapter import (
    agui_history,
    agui_prompt,
    run_error_event,
    run_finished_event,
    run_started_event,
    sse_event,
    text_message_events,
    tool_trace_events,
    ui_command_events,
)
from .config import load_runtime_settings, get_available_models
from .graph import run_agent, stream_agent
from .mcp_server import build_mcp_server
from .schemas import AGUIActorPayload, AGUIRunAgentInput, ChatRequest, ChatResponse


mcp_server = build_mcp_server()


def _prompt_hash(prompt: str) -> str:
    if not prompt:
        return ""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _agui_signature_payload(payload: AGUIActorPayload) -> str:
    actor = payload.actor
    signed_payload = {
        "actor": {
            "actor_version": actor.actor_version,
            "channel": actor.channel,
            "is_superuser": actor.is_superuser,
            "origin_channel": actor.origin_channel,
            "roles": list(actor.roles or []),
            "source": actor.source,
            "user_id": actor.user_id,
            "username": actor.username,
        },
        "actor_version": payload.actor_version,
        "issued_at": payload.issued_at,
        "model_id": payload.model_id,
        "origin_channel": payload.origin_channel,
        "session_id": payload.session_id,
    }
    return json.dumps(signed_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _agui_signature_is_valid(payload: AGUIActorPayload) -> bool:
    settings = load_runtime_settings()
    token = settings.django_gateway_token or ""
    if not token or not payload.signature or not payload.issued_at:
        return False
    ttl_seconds = int(os.environ.get("LOCAL_BUSINESS_COPILOTKIT_ACTOR_TOKEN_TTL_SECONDS", "900"))
    if abs(int(time.time()) - int(payload.issued_at)) > ttl_seconds:
        return False
    expected = hmac.new(
        token.encode("utf-8"),
        _agui_signature_payload(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, payload.signature)


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


@app.post("/ag-ui")
async def ag_ui_run(run_input: AGUIRunAgentInput):
    logger = logging.getLogger(__name__)
    forwarded = run_input.forwardedProps or {}
    try:
        actor_payload = AGUIActorPayload.model_validate(forwarded)
    except Exception as exc:
        logger.warning(
            "AG-UI request rejected: run_id=%s thread_id=%s error_type=%s",
            run_input.runId,
            run_input.threadId,
            exc.__class__.__name__,
        )

        async def invalid_actor_events():
            yield sse_event(run_error_event("Контекст исполнителя AG-UI недействителен.", code="invalid_actor"))

        return StreamingResponse(invalid_actor_events(), media_type="text/event-stream")

    if not _agui_signature_is_valid(actor_payload):
        logger.warning(
            "AG-UI request rejected by actor signature: run_id=%s thread_id=%s user_id=%s",
            run_input.runId,
            run_input.threadId,
            actor_payload.actor.user_id,
        )

        async def invalid_signature_events():
            yield sse_event(run_error_event("Подпись контекста исполнителя AG-UI недействительна.", code="invalid_actor_signature"))

        return StreamingResponse(invalid_signature_events(), media_type="text/event-stream")

    actor_context = actor_payload.actor.ensure_trace_context()
    actor = actor_context.model_dump()
    if actor_payload.page_context:
        actor["page_context"] = actor_payload.page_context
    prompt = agui_prompt(run_input)
    history = agui_history(run_input)
    log_context = {
        "thread_id": run_input.threadId,
        "run_id": run_input.runId,
        "session_id": actor_payload.session_id or run_input.threadId,
        "conversation_id": actor_context.conversation_id,
        "request_id": actor_context.request_id,
        "origin_channel": actor_payload.origin_channel,
        "model_id": actor_payload.model_id,
        "prompt_sha256": _prompt_hash(prompt),
        "prompt_length": len(prompt),
        "history_count": len(history),
        "actor_user_id": actor_context.user_id,
        "actor_channel": actor_context.channel,
        "actor_is_superuser": actor_context.is_superuser,
        "actor_roles_count": len(actor_context.roles or []),
        "page_context_present": bool(actor.get("page_context")),
    }
    logger.info("Agent runtime AG-UI request: %s", log_context)

    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")

    async def event_generator():
        message_id = f"msg_{run_input.runId}"
        try:
            yield sse_event(run_started_event(run_input))
            result = run_agent(
                actor=actor,
                session_id=actor_payload.session_id or run_input.threadId,
                prompt=prompt,
                history=history,
                conversation_id=actor_context.conversation_id,
                request_id=actor_context.request_id,
                origin_channel=actor_payload.origin_channel,
                actor_version=actor_payload.actor_version,
                model_id=actor_payload.model_id,
            )
            for event in text_message_events([result.get("assistant_message", "")], message_id=message_id):
                yield sse_event(event)
            for event in tool_trace_events(result.get("tool_trace", []), parent_message_id=message_id):
                yield sse_event(event)
            for event in ui_command_events(result.get("ui_commands", [])):
                yield sse_event(event)
            yield sse_event(
                run_finished_event(
                    run_input,
                    result={
                        "conversation_id": actor_context.conversation_id,
                        "request_id": actor_context.request_id,
                    },
                )
            )
        except Exception as exc:
            logger.error(
                "Agent runtime AG-UI failed: request_id=%s conversation_id=%s error_type=%s",
                actor_context.request_id,
                actor_context.conversation_id,
                exc.__class__.__name__,
            )
            yield sse_event(run_error_event("ИИ-сервис вернул ошибку."))

    return StreamingResponse(event_generator(), media_type="text/event-stream")


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
