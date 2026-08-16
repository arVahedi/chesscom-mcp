# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

ARG PYTHON_IMAGE=python:3.12-slim@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65

FROM ${PYTHON_IMAGE} AS builder

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

WORKDIR /build

RUN python -m venv "${VIRTUAL_ENV}"

COPY requirements.txt requirements-build.txt ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.txt \
    && python -m pip install --no-cache-dir --require-hashes -r requirements-build.txt

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir --no-deps --no-build-isolation . \
    && python -m pip uninstall --yes pip setuptools wheel


FROM ${PYTHON_IMAGE} AS runtime

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 chessmcp \
    && useradd --uid 10001 --gid chessmcp --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin chessmcp \
    && rm -rf /usr/local/lib/python3.12/site-packages/pip /usr/local/lib/python3.12/site-packages/pip-* \
        /usr/local/lib/python3.12/site-packages/setuptools /usr/local/lib/python3.12/site-packages/setuptools-* \
        /usr/local/lib/python3.12/site-packages/wheel /usr/local/lib/python3.12/site-packages/wheel-* \
        /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.12 \
        /usr/bin/apt /usr/bin/apt-get /usr/bin/apt-cache /usr/bin/apt-config /usr/bin/apt-mark \
        /usr/lib/apt /var/lib/apt /var/cache/apt /var/lib/dpkg

COPY --from=builder --chown=10001:10001 /opt/venv /opt/venv

USER 10001:10001
WORKDIR /app

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import http.client,os; c=http.client.HTTPConnection('127.0.0.1',int(os.getenv('CHESS_COM_MCP_PORT','8765')),timeout=3); c.request('GET','/healthz',headers={'Host':os.environ['CHESS_COM_MCP_ALLOWED_HOSTS'].split(',')[0].strip()}); r=c.getresponse(); raise SystemExit(0 if r.status==200 and r.read()==b'{\"status\":\"ok\"}' else 1)"]

ENTRYPOINT ["chess-com-mcp"]
CMD ["--transport", "http"]
