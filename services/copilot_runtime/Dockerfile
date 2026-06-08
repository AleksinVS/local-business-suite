FROM node:22-slim

ENV NODE_ENV=production
ENV COPILOTKIT_TELEMETRY_DISABLED=true

WORKDIR /app

COPY package.json package-lock.json /app/
RUN npm ci --omit=dev --legacy-peer-deps

COPY services/copilot_runtime/ /app/services/copilot_runtime/

RUN useradd --uid 1000 --create-home --home-dir /home/app app \
    && chown -R app:app /app

USER app

CMD ["node", "services/copilot_runtime/server.mjs"]
