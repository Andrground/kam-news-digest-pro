"""Espera o banco e o Ollama, e garante que o modelo esteja baixado.

Executado pelo entrypoint antes de subir a aplicação:

    python -m kamnews.bootstrap
"""

import sys
import time

import httpx
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from kamnews.settings import DEV_SECRET_KEY, Settings

WAIT_TIMEOUT = 300
POLL_SECONDS = 2
PROBE_TIMEOUT = 5


def checar_secret_key(settings: Settings) -> bool:
    """Vazia é fatal; a de desenvolvimento só avisa.

    O compose resolve `${SECRET_KEY}` para string vazia quando o .env
    não existe. Sem esta checagem, a aplicação subiria assinando tokens
    com chave vazia — e ninguém perceberia.
    """
    if not settings.SECRET_KEY:
        print('=' * 70, flush=True)
        print(
            'ERRO: SECRET_KEY vazia. Provavelmente falta o arquivo .env\n'
            '(copie de .env.example) ou a variável não foi preenchida.\n'
            'Gere uma com: openssl rand -hex 32',
            flush=True,
        )
        print('=' * 70, flush=True)
        return False

    if settings.SECRET_KEY == DEV_SECRET_KEY:
        print('=' * 70, flush=True)
        print(
            'ATENÇÃO: SECRET_KEY de desenvolvimento em uso. Qualquer um '
            'que conheça\neste valor consegue forjar tokens. Antes de '
            'expor a aplicação para fora\ndo localhost, gere uma nova '
            'com: openssl rand -hex 32',
            flush=True,
        )
        print('=' * 70, flush=True)

    return True


def _wait_for_db(url: str) -> bool:
    deadline = time.monotonic() + WAIT_TIMEOUT
    print('Aguardando o banco de dados ...', flush=True)
    engine = create_engine(url)
    while time.monotonic() < deadline:
        try:
            with engine.connect():
                return True
        except OperationalError:
            time.sleep(POLL_SECONDS)
    return False


def _wait_for_server(host: str) -> bool:
    deadline = time.monotonic() + WAIT_TIMEOUT
    print(f'Aguardando o Ollama em {host} ...', flush=True)
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f'{host}/api/tags', timeout=PROBE_TIMEOUT)
            resp.raise_for_status()
            return True
        except httpx.HTTPError:
            time.sleep(POLL_SECONDS)
    return False


def _has_model(host: str, model: str) -> bool:
    try:
        resp = httpx.get(f'{host}/api/tags', timeout=PROBE_TIMEOUT)
        resp.raise_for_status()
        installed = {
            (item.get('name') or '').split(':')[0]
            for item in resp.json().get('models', [])
        }
    except (httpx.HTTPError, ValueError):
        return False
    return model.split(':', maxsplit=1)[0] in installed


def _pull(host: str, model: str) -> None:
    print(
        f'Baixando o modelo {model} (pode demorar na primeira vez) ...',
        flush=True,
    )
    last = ''
    with httpx.stream(
        'POST',
        f'{host}/api/pull',
        json={'name': model},
        timeout=None,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            status = line[:120]
            if status != last:
                print(f'  {status}', flush=True)
                last = status


def main() -> int:
    settings = Settings()
    host = settings.OLLAMA_HOST.rstrip('/')
    model = settings.OLLAMA_MODEL

    if not checar_secret_key(settings):
        return 1

    # O banco primeiro: é rápido, e falhar aqui é melhor do que falhar
    # depois de um pull de modelo de vários minutos.
    if not _wait_for_db(settings.DATABASE_URL):
        print('Banco de dados não respondeu a tempo.', flush=True)
        return 1

    if not _wait_for_server(host):
        print('Ollama não respondeu a tempo.', flush=True)
        return 1

    if _has_model(host, model):
        print(f'Modelo {model} já disponível.', flush=True)
        return 0

    try:
        _pull(host, model)
    except httpx.HTTPError as err:
        print(f'Falha ao baixar o modelo: {err}', flush=True)
        return 1

    print('Modelo pronto.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
