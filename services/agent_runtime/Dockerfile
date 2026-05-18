FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY services/agent_runtime/requirements.txt /tmp/agent-runtime-requirements.txt
RUN pip install --no-cache-dir -r /tmp/agent-runtime-requirements.txt

COPY services/ /app/services/
COPY contracts/ /app/contracts/
COPY apps/ai/tool_definitions.py /app/apps/ai/tool_definitions.py
COPY apps/ai/__init__.py /app/apps/ai/__init__.py
COPY apps/__init__.py /app/apps/__init__.py

RUN useradd --uid 1000 --create-home --home-dir /home/app app \
    && chown -R app:app /app

USER app

CMD ["uvicorn", "services.agent_runtime.app:app", "--host", "0.0.0.0", "--port", "8090"]
