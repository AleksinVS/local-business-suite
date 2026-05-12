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
    init_kwargs = {"temperature": 0}
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

    @task
    def call_llm(messages):
        return model_with_tools.invoke([SystemMessage(content=current_instructions["body"])] + messages)

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
    init_kwargs = {"temperature": 0}
    if resolved.provider:
        init_kwargs["model_provider"] = resolved.provider
    if resolved.api_key:
        init_kwargs["api_key"] = resolved.api_key
    if resolved.base_url:
        init_kwargs["base_url"] = resolved.base_url
    model = init_chat_model(resolved.model, **init_kwargs)
    model_with_tools = model.bind_tools(tools)
    system_prompt = build_system_prompt()

    @task
    def call_llm(messages):
        return model_with_tools.invoke([SystemMessage(content=system_prompt)] + messages)

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
