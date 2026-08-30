"""Общее безопасное преобразование контрактной палитры в CSS-переменные."""

from __future__ import annotations

import re


_CSS_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def status_color_css_variables(payload, *, prefix):
    """Вернуть inline CSS только из безопасных кодов статуса и HEX-цветов."""

    if not _CSS_NAME.fullmatch(prefix):
        raise ValueError("Префикс CSS-переменной содержит недопустимые символы.")

    declarations = []
    statuses = payload.get("statuses", {}) if isinstance(payload, dict) else {}
    for status, config in statuses.items():
        if not isinstance(status, str) or not _CSS_NAME.fullmatch(status):
            continue
        if not isinstance(config, dict):
            continue
        color = config.get("color")
        background = config.get("background")
        if isinstance(color, str) and _HEX_COLOR.fullmatch(color):
            declarations.append(f"--{prefix}-{status}: {color}")
        if isinstance(background, str) and _HEX_COLOR.fullmatch(background):
            declarations.append(f"--{prefix}-{status}-bg: {background}")
    return "; ".join(declarations)
