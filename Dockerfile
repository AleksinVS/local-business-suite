FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data/db /app/data/media /app/data/logs /app/data/contracts /app/staticfiles
RUN chmod +x /app/docker/entrypoint.prod.sh

CMD ["/app/docker/entrypoint.prod.sh"]
