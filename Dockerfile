# One Cloud Run service serves both the API and the PWA. Relative /api paths in
# the app then need no CORS, no second deployment and no separate origin — which
# also means the $150 of credits only ever pays for one scale-to-zero service.

FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY --from=web /web/dist ./web
EXPOSE 8080
# JSON form so signals reach the process; `exec` inside sh keeps uvicorn as PID 1
# while still letting Cloud Run inject $PORT.
CMD ["/bin/sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
