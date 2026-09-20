# GENESIS experiment sandbox.
# Runs untrusted, AI-generated experiment code. Deliberately minimal: no build
# tools, no shell utilities beyond the base image, no credentials, no network
# at run time (the container is started with `--network none`).
FROM python:3.12-slim

# Pinned scientific stack. Experiments may import ONLY these.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -rf /root/.cache /tmp/requirements.txt

# Non-root user. The runner also passes --user 1000:1000 and --cap-drop ALL.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin sandbox
USER sandbox

WORKDIR /work

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1

# The runner overrides this; it is here so the image is runnable on its own.
CMD ["python", "-E", "-s", "_bootstrap.py"]
