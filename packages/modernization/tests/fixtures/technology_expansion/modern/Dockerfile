# AutoForge Multi-Stage Production Dockerfile
FROM python:3.12-slim AS build-stage
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

FROM python:3.12-slim AS runtime-stage
WORKDIR /app
COPY --from=build-stage /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build-stage /usr/local/bin /usr/local/bin
COPY . /app
USER 1000:1000
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1
ENTRYPOINT ["python", "main.py"]
