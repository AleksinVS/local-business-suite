from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.func import entrypoint, task
from langgraph.graph import add_messages

from .config import load_runtime_settings
from .gateway_client import DjangoGatewayClient
from .prompting import build_system_prompt
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


def run_agent(*, actor: dict, session_id: str, prompt: str, history):
    settings = load_runtime_settings()
    gateway_client = DjangoGatewayClient(
        base_url=settings.django_gateway_url,
        token=settings.django_gateway_token,
    )
    tools = build_tools(actor=actor, session_id=session_id, gateway_client=gateway_client)
    tools_by_name = {tool.name: tool for tool in tools}
    model = init_chat_model(settings.model, temperature=0)
    model_with_tools = model.bind_tools(tools)
    system_prompt = build_system_prompt()
    tool_trace = []

    @task
    def call_llm(messages):
        return model_with_tools.invoke([SystemMessage(content=system_prompt)] + messages)

    @task
    def call_tool(tool_call):
        tool = tools_by_name[tool_call["name"]]
        result = tool.invoke(tool_call)
        tool_trace.append({"tool": tool_call["name"], "args": tool_call.get("args", {})})
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
    return {"assistant_message": assistant_message, "tool_trace": tool_trace}
