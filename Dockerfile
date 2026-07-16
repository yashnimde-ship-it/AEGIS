FROM python:3.11-slim

WORKDIR /app

# Install dependencies first for layer caching
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ .

# Copy dashboard static files so FastAPI can serve them at /dashboard
COPY dashboard/ ./dashboard/

# Copy Atlas engine and incident corpus (importable as atlas.atlas from /app/)
COPY atlas/ ./atlas/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
