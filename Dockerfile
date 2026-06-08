FROM node:22-slim AS copilotkit-assets

WORKDIR /app

COPY package.json package-lock.json vite.copilotkit.config.mjs /app/
COPY static/src/copilotkit/ /app/static/src/copilotkit/
RUN npm ci --legacy-peer-deps \
    && npm run build:copilotkit

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/ /app/apps/
COPY config/ /app/config/
COPY contracts/ /app/contracts/
COPY docker/ /app/docker/
COPY static/ /app/static/
COPY --from=copilotkit-assets /app/static/dist/copilotkit /app/static/dist/copilotkit
COPY templates/ /app/templates/
COPY workflow/ai_artifacts/ /app/workflow/ai_artifacts/
COPY manage.py /app/manage.py
COPY pytest.ini /app/pytest.ini

RUN chmod +x /app/docker/entrypoint.prod.sh \
    && useradd --uid 1000 --create-home --home-dir /home/app app \
    && chown -R app:app /app

USER app

CMD ["/app/docker/entrypoint.prod.sh"]
