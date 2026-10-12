FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# libgomp1: shared runtime some numeric wheels expect; harmless if unused.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt -r /app/backend/requirements.txt

COPY engine /app/engine
COPY backend /app/backend
COPY sample_data /app/sample_data

RUN useradd --create-home --uid 10001 airops && chown -R airops /app
USER airops

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

# One uvicorn process on purpose: the solver pool and job bookkeeping live inside it.
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
