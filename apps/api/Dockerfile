FROM python:3.12-slim

WORKDIR /app

COPY apps/api/requirements.txt ./apps/api/requirements.txt
RUN pip install --no-cache-dir -r apps/api/requirements.txt

# Mirror the repository layout. The API copies sandbox/bootstrap.py and the
# dataset module into each experiment's working directory at run time, and it
# locates them by searching upward for those paths -- so the tree shape here
# must match the repo.
COPY apps/api/genesis ./apps/api/genesis
COPY apps/api/scripts ./apps/api/scripts
COPY sandbox ./sandbox
COPY experiments ./experiments

WORKDIR /app/apps/api

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn genesis.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
