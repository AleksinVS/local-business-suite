import concurrent.futures
import logging
import uuid

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.func import entrypoint, task
from langgraph.graph import add_messages

logger = logging.getLogger(__name__)

from .config import load_runtime_settings, resolve_model
from .gateway_client import DjangoGatewayClient
from .prompting import build_system_prompt
from .task_types import resolve_task_type_for_tool
from .tools import build_tools

# Absolute wall-clock deadline for a single LLM call. LangChain's
# `init_chat_model(..., timeout=120)` sets a per-request timeout on the
# underlying httpx client, but in streaming mode httpx resets that
# timer on every chunk the server sends. A slow LLM provider that
# trickles one chunk every 30s can keep the call "alive" forever
# without ever tripping the per-request timeout, so the uvicorn
# worker blocks indefinitely. The ThreadPoolExecutor wrapper below
# enforces a real deadline that the streaming timeouts cannot escape.
LLM_DEADLINE_SECONDS = 120


def _invoke_chat_model_with_deadline(invoke, messages):
    """Run ``invoke`` in a worker thread with a hard wall-clock deadline.

    On timeout we cancel the future (best-effort: Python cannot kill
    a running C-level httpx read, but cancelling the future drops the
    reference so the executor reclaims the thread) and raise a
    RuntimeError that the LangGraph agent surfaces to the user as a
    chat_runtime_error. The user gets a clean failure within
    LLM_DEADLINE_SECONDS + a small overhead instead of an indefinitely
    stuck chat.
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(invoke, messages)
    try:
        return future.result(timeout=LLM_DEADLINE_SECONDS)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        logger.error(
            "LLM call exceeded %ss absolute deadline; cancelling future",
            LLM_DEADLINE_SECONDS,
        )
        raise RuntimeError(
            f"LLM call exceeded {LLM_DEADLINE_SECONDS}s deadline"
        ) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _extract_ui_command(tool_result):
    """Pull the `ui_command` descriptor out of a tool's return value.

    LangChain's `@tool` decorator wraps the function return into a
    `ToolMessage`. By default the return dict is serialised into
    `.content` (as a Python `repr()` string) and `.artifact` is left
    as None unless the function declares
    `tool_config={"response_format": "content_and_artifact"}` and
    returns a `(content, artifact)` tuple. Older call sites that
    bypass the tool framework may still return the raw dict. We
    accept all three shapes.
    """
    artifact = getattr(tool_result, "artifact", None)
    if isinstance(artifact, dict):
        tool_result = artifact
    elif not isinstance(tool_result, dict):
        # LangChain stores the tool's return value in `.content` as a
        # string. Older versions used json.dumps (double quotes), the
        # current one uses repr() (single quotes). Try both.
        content = getattr(tool_result, "content", None)
        if isinstance(content, str):
            try:
                import json as _json
                tool_result = _json.loads(content)
            except (ValueError, TypeError):
                try:
                    import ast
                    tool_result = ast.literal_eval(content)
                except (ValueError, SyntaxError):
                    return None
        else:
            return None
    if not isinstance(tool_result, dict):
        return None
    result = tool_result.get("result")
    if not isinstance(result, dict):
        return None
    command = result.get("ui_command")
    if isinstance(command, dict) and command.get("type") == "open_right_panel":
        return command
    return None


def _history_to_messages(history):
    messages = []
    for item in history:
        if item.role == "user":
            messages.append(HumanMessage(content=item.content))
        elif item.role == "assistant":
            messages.append(AIMessage(content=item.content))
        elif item.role == "tool":
            messages.append(ToolMessage(content=item.content, tool_call_id=item.tool_name or "tool"))
    return messages


def run_agent(
    *,
    actor: dict,
    session_id: str,
    prompt: str,
    history,
    conversation_id: str = "",
    request_id: str = "",
    origin_channel: str = "",
    actor_version: str = "",
    model_id: str = "",
):
    """
    Run the LangGraph agent for a single user prompt.
    """
    settings = load_runtime_settings()
    resolved = resolve_model(model_id)

    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    if not request_id:
        request_id = str(uuid.uuid4())
    if not origin_channel:
        origin_channel = actor.get("channel", "internal")

    gateway_client = DjangoGatewayClient(
        base_url=settings.django_gateway_url,
        token=settings.django_gateway_token,
    )

    # 1. Fetch skills catalog
    skills_catalog = gateway_client.get_skills_catalog().get("skills", [])
    
    tools = build_tools(
        actor=actor,
        session_id=session_id,
        gateway_client=gateway_client,
        conversation_id=conversation_id,
        request_id=request_id,
        origin_channel=origin_channel,
        actor_version=actor_version,
    )
    tools_by_name = {tool.name: tool for tool in tools}
    init_kwargs = {"temperature": 0, "timeout": 120}
    if resolved.provider:
        init_kwargs["model_provider"] = resolved.provider
    if resolved.api_key:
        init_kwargs["api_key"] = resolved.api_key
    if resolved.base_url:
        init_kwargs["base_url"] = resolved.base_url
    model = init_chat_model(resolved.model, **init_kwargs)
    model_with_tools = model.bind_tools(tools)

    # Dynamic state for instructions
    current_instructions = {"body": build_system_prompt(skills_catalog=skills_catalog)}
    tool_trace = []
    ui_commands = []

    @task
    def call_llm(messages):
        return _invoke_chat_model_with_deadline(
            model_with_tools.invoke,
            [SystemMessage(content=current_instructions["body"])] + messages,
        )

    @task
    def call_tool(tool_call):
        tool_name = tool_call["name"]
        tool_call_id = tool_call.get("id", str(uuid.uuid4()))
        try:
            tool = tools_by_name[tool_name]
            result = tool.invoke(tool_call)
        except Exception as exc:
            logger.error("Tool %s failed: %s", tool_name, exc)
            return ToolMessage(content=f"Error: {exc}", tool_call_id=tool_call_id)

        # Handle skill activation specially
        if tool_name == "activate_skill" and isinstance(result, dict) and result.get("ok"):
            current_instructions["body"] = build_system_prompt(
                skills_catalog=skills_catalog,
                active_skill_content=result.get("instructions", "")
            )

        slot_values = tool_call.get("args", {})
        resolution = resolve_task_type_for_tool(tool_name, slot_values)

        trace_entry = {
            "tool": tool_name,
            "args": slot_values,
            "conversation_id": conversation_id,
            "request_id": request_id,
            "origin_channel": origin_channel,
            "actor_version": actor_version,
        }
        if resolution:
            trace_entry.update(resolution.to_trace_dict())
        tool_trace.append(trace_entry)
        ui_command = _extract_ui_command(result)
        if ui_command:
            ui_commands.append(ui_command)
        return result

    @entrypoint()
    def agent(messages):
        model_response = call_llm(messages).result()
        while True:
            if not model_response.tool_calls:
                break
            tool_results = [call_tool(tool_call).result() for tool_call in model_response.tool_calls]
            messages = add_messages(messages, [model_response, *tool_results])
            model_response = call_llm(messages).result()
        return add_messages(messages, [model_response])

    history_messages = _history_to_messages(history)
    history_messages.append(HumanMessage(content=prompt))
    result_messages = agent.invoke(history_messages)
    assistant_message = result_messages[-1].content if result_messages else ""
    return {
        "assistant_message": assistant_message,
        "tool_trace": tool_trace,
        "ui_commands": ui_commands,
        "conversation_id": conversation_id,
        "request_id": request_id,
    }


def stream_agent(
    *,
    actor: dict,
    session_id: str,
    prompt: str,
    history,
    conversation_id: str = "",
    request_id: str = "",
    origin_channel: str = "",
    actor_version: str = "",
    model_id: str = "",
):
    """
    Stream the LangGraph agent for a single user prompt.
    Yields chunks of text or tool execution events.
    """
    settings = load_runtime_settings()
    resolved = resolve_model(model_id)

    if not conversation_id:
        conversation_id = str(uuid.uuid4())
    if not request_id:
        request_id = str(uuid.uuid4())
    if not origin_channel:
        origin_channel = actor.get("channel", "internal")

    gateway_client = DjangoGatewayClient(
        base_url=settings.django_gateway_url,
        token=settings.django_gateway_token,
    )

    # Fetch skills catalog so the system prompt includes available skills
    skills_catalog = gateway_client.get_skills_catalog().get("skills", [])

    tools = build_tools(
        actor=actor,
        session_id=session_id,
        gateway_client=gateway_client,
        conversation_id=conversation_id,
        request_id=request_id,
        origin_channel=origin_channel,
        actor_version=actor_version,
    )
    tools_by_name = {tool.name: tool for tool in tools}
    init_kwargs = {"temperature": 0, "timeout": 120}
    if resolved.provider:
        init_kwargs["model_provider"] = resolved.provider
    if resolved.api_key:
        init_kwargs["api_key"] = resolved.api_key
    if resolved.base_url:
        init_kwargs["base_url"] = resolved.base_url
    model = init_chat_model(resolved.model, **init_kwargs)
    model_with_tools = model.bind_tools(tools)

    # Dynamic state for instructions — updated when activate_skill succeeds
    current_instructions = {"body": build_system_prompt(skills_catalog=skills_catalog)}
    tool_trace = []
    ui_commands = []

    @task
    def call_llm(messages):
        return _invoke_chat_model_with_deadline(
            model_with_tools.invoke,
            [SystemMessage(content=current_instructions["body"])] + messages,
        )

    @task
    def call_tool(tool_call):
        tool_name = tool_call["name"]
        tool_call_id = tool_call.get("id", str(uuid.uuid4()))
        try:
            tool = tools_by_name[tool_name]
            result = tool.invoke(tool_call)
        except Exception as exc:
            logger.error("Tool %s failed: %s", tool_name, exc)
            return ToolMessage(content=f"Error: {exc}", tool_call_id=tool_call_id)

        # Handle skill activation — dynamically update the system prompt
        if tool_name == "activate_skill" and isinstance(result, dict) and result.get("ok"):
            current_instructions["body"] = build_system_prompt(
                skills_catalog=skills_catalog,
                active_skill_content=result.get("instructions", "")
            )

        slot_values = tool_call.get("args", {})
        resolution = resolve_task_type_for_tool(tool_name, slot_values)

        trace_entry = {
            "tool": tool_name,
            "args": slot_values,
            "conversation_id": conversation_id,
            "request_id": request_id,
            "origin_channel": origin_channel,
            "actor_version": actor_version,
        }
        if resolution:
            trace_entry.update(resolution.to_trace_dict())
        tool_trace.append(trace_entry)
        ui_command = _extract_ui_command(result)
        if ui_command:
            ui_commands.append(ui_command)
        return result

    @entrypoint()
    def agent(messages):
        model_response = call_llm(messages).result()
        while True:
            if not model_response.tool_calls:
                break
            tool_results = [call_tool(tool_call).result() for tool_call in model_response.tool_calls]
            messages = add_messages(messages, [model_response, *tool_results])
            model_response = call_llm(messages).result()
        return add_messages(messages, [model_response])

    history_messages = _history_to_messages(history)
    history_messages.append(HumanMessage(content=prompt))
    history_ai_count = sum(1 for m in history_messages if isinstance(m, AIMessage))

    ai_yielded = 0
    for chunk in agent.stream(history_messages, stream_mode="messages"):
        if isinstance(chunk, tuple) and len(chunk) >= 2:
            msg = chunk[0]
            if not isinstance(msg, AIMessage) or msg.tool_calls:
                continue
            ai_yielded += 1
            if ai_yielded <= history_ai_count:
                continue
            yield msg.content
    for command in ui_commands:
        yield {"ui_command": command}
