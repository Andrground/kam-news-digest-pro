#!/bin/sh
set -e

export PYTHONPATH=/app/src

# Espera o banco e o Ollama; baixa o modelo se preciso.
poetry run python -m kamnews.bootstrap

# Migracoes e dados iniciais.
poetry run alembic upgrade head
poetry run python -m kamnews.seed

# Sobe a aplicacao.
exec poetry run fastapi run src/kamnews/app.py --host 0.0.0.0 --port 8000
