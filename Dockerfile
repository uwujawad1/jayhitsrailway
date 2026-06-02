FROM node:20-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-pip ca-certificates socat \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY requirements.txt ./
RUN python3 -m pip install --break-system-packages --no-cache-dir -r requirements.txt

COPY . .

RUN npm run build

EXPOSE 8000

CMD ["sh", "-c", "APP_PORT=${PORT:-8000}; echo \"Starting JayHits on port ${APP_PORT}\"; if [ \"${APP_PORT}\" != \"8000\" ]; then echo \"Forwarding public port 8000 to ${APP_PORT}\"; socat TCP-LISTEN:8000,fork,reuseaddr TCP:127.0.0.1:${APP_PORT} & fi; python3 -m uvicorn railway_backend:app --host 0.0.0.0 --port ${APP_PORT}"]
