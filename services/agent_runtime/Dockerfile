FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOME=/home/app

WORKDIR /app

# Собственный lock: agent-runtime собирается из отдельного минимального
# requirements.txt (не из корневого), поэтому и зафиксированные транзитивные
# версии должны быть отдельными — иначе пришлось бы тянуть в образ пакеты
# корневого requirements.lock (Django, gevent, Pillow, psycopg и т.д.), не
# нужные этому сервису. requirements.txt остаётся человекочитаемым входом для
# `make lock-agent-runtime` / pip-compile.
COPY services/agent_runtime/requirements.txt /tmp/agent-runtime-requirements.txt
COPY services/agent_runtime/requirements.lock /tmp/agent-runtime-requirements.lock
RUN pip install --no-cache-dir -r /tmp/agent-runtime-requirements.lock

COPY services/ /app/services/
COPY contracts/ /app/contracts/
COPY apps/ai/tool_definitions.py /app/apps/ai/tool_definitions.py
COPY apps/ai/__init__.py /app/apps/ai/__init__.py
COPY apps/__init__.py /app/apps/__init__.py

RUN mkdir -p /home/app \
    && if ! getent passwd 1000 >/dev/null; then useradd --uid 1000 --create-home --home-dir /home/app app; fi \
    && chown -R 1000:1000 /app /home/app

USER 1000

CMD ["uvicorn", "services.agent_runtime.app:app", "--host", "0.0.0.0", "--port", "8090"]
