FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
COPY backend/pyproject.toml backend/uv.lock backend/
# Behind a TLS-inspecting proxy the build cannot verify PyPI. If a corporate root certificate is supplied as the
# build secret `corp_ca`, trust it for this one step only. It is a build secret, so it is not stored in any layer.
RUN --mount=type=secret,id=corp_ca \
    set -e; \
    if [ -s /run/secrets/corp_ca ]; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/corp_ca > /tmp/build-bundle.pem; \
      export SSL_CERT_FILE=/tmp/build-bundle.pem UV_NATIVE_TLS=1; \
    fi; \
    cd backend && uv sync --frozen --no-dev --no-install-project; \
    rm -f /tmp/build-bundle.pem
COPY backend/app backend/app
COPY frontend frontend
COPY config config
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh && useradd -m goip && mkdir -p data && chown -R goip /app/data /app/config
USER goip
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8001/health')"
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["backend/.venv/bin/python", "-m", "app.main"]
