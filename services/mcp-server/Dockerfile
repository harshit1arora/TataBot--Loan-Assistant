# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10010 app && chown -R app:app /srv
USER app
EXPOSE 8765
# Streamable HTTP so the agent service can reach the tools over the network.
CMD ["python", "-m", "mcp_server", "--http", "--port", "8765"]
