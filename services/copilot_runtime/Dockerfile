FROM node:22-slim

ENV NODE_ENV=production
ENV COPILOTKIT_TELEMETRY_DISABLED=true
ENV HOME=/home/app

WORKDIR /app

COPY package.json package-lock.json /app/
RUN npm ci --omit=dev --legacy-peer-deps

COPY services/copilot_runtime/ /app/services/copilot_runtime/

RUN mkdir -p /home/app \
    && if ! getent passwd 1000 >/dev/null; then useradd --uid 1000 --create-home --home-dir /home/app app; fi \
    && chown -R 1000:1000 /app /home/app

USER 1000

CMD ["node", "services/copilot_runtime/server.mjs"]
