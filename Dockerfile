FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY bench ./bench
RUN pip install --no-cache-dir .
EXPOSE 8400
VOLUME ["/config", "/data"]
CMD ["keel", "serve", "--config", "/config/keel.yaml", "--host", "0.0.0.0", "--port", "8400"]
