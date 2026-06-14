FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml requirements.txt ./
COPY src/ src/

RUN pip install --no-cache-dir . \
    && pip install --no-cache-dir spacy \
    && python -m spacy download en_core_web_sm

# Vault lives in a volume so mappings survive container restarts
VOLUME ["/data"]
ENV HIPAA_BRIDGE_VAULT=/data/vault.db

EXPOSE 8484

# Backend defaults to host Ollama; override with --backend or env
ENTRYPOINT ["hipaa-bridge", "--vault", "/data/vault.db"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8484", "--backend", "http://host.docker.internal:11434"]
