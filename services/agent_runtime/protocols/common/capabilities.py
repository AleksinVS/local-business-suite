import os


DEFAULT_AGUI_PROFILE = "ag-ui@0.0.55"
DEFAULT_LOCAL_BUSINESS_PROTOCOL_VERSION = "1.0"
LOCAL_BUSINESS_EXTENSIONS = (
    "ui_command.open_right_panel.v1",
    "page_context.envelope.v1",
)


def protocol_metadata_value(*, driver: str = "") -> dict[str, object]:
    return {
        "agui_profile": os.environ.get("LOCAL_BUSINESS_AI_UI_AGUI_PROFILE", DEFAULT_AGUI_PROFILE),
        "local_business_protocol": os.environ.get(
            "LOCAL_BUSINESS_AI_UI_PROTOCOL_VERSION",
            DEFAULT_LOCAL_BUSINESS_PROTOCOL_VERSION,
        ),
        "driver": driver or "unknown",
        "extensions": list(LOCAL_BUSINESS_EXTENSIONS),
    }
