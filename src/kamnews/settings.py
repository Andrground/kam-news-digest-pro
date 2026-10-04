from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Valor de SECRET_KEY que indica ambiente de desenvolvimento. O
# bootstrap avisa quando detecta este valor — em produção, gere um novo
# com `openssl rand -hex 32`.
DEV_SECRET_KEY = 'dev-only-trocar-em-producao'

# Teto do período de busca de notícias. Não é env de propósito: é regra
# do produto, e o frontend repete o mesmo número nos atalhos.
MAX_PERIODO_DIAS = 60

# Brasília (sem horário de verão desde 2019). Fuso fixo em vez de
# ZoneInfo: a imagem slim não traz o banco tz do sistema.
FUSO_BR = timezone(timedelta(hours=-3))


def hoje_br() -> date:
    """Data de hoje no Brasil — a do KAM, não a do servidor em UTC."""
    return datetime.now(FUSO_BR).date()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env', env_file_encoding='utf-8', extra='ignore'
    )

    # Banco de dados (Postgres)
    DATABASE_URL: str = (
        'postgresql+psycopg://kamnews:kamnews@localhost:5432/kamnews'
    )

    # Autenticação (JWT)
    SECRET_KEY: str = DEV_SECRET_KEY
    ALGORITHM: str = 'HS256'
    # 8h: uma busca leva minutos e o KAM fica na página o dia todo.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # Seed: admin inicial e senha padrão dos KAMs.
    # O domínio precisa ser válido para o EmailStr: TLDs de uso especial
    # (.local, .internal) são rejeitados pelo email-validator.
    SEED_EMAIL_DOMAIN: str = 'kamnews.com.br'
    MASTER_EMAIL: str = 'admin@kamnews.com.br'
    MASTER_PASSWORD: str = 'admin123'
    SEED_KAM_PASSWORD: str = 'kamnews123'

    # Assistente (chat). Diferente do resto do projeto, este caminho usa
    # um modelo na nuvem: um chat precisa responder em segundos, e o
    # Ollama local leva dezenas deles. Sem a chave, a aba fica desligada.
    GROQ_API_KEY: str = ''
    # Confira os modelos da sua conta: GET /openai/v1/models na Groq.
    # O catálogo muda, e um modelo indisponível devolve 404.
    CHAT_MODEL: str = 'openai/gpt-oss-120b'
    CHAT_TIMEOUT: int = 60
    # Teto de notícias no contexto; acima disso o prompt fica caro e o
    # modelo perde o foco.
    CHAT_MAX_NOTICIAS: int = 60
    # Conversas mais antigas que isso são apagadas.
    CHAT_HISTORY_DAYS: int = 7
    # Teto de caracteres extraídos de uma página lida pelo assistente.
    CHAT_MAX_PAGINA_CHARS: int = 6000

    # Ollama (modelo local — sem custo, sem chave)
    OLLAMA_HOST: str = 'http://localhost:11434'
    OLLAMA_MODEL: str = 'llama3.2'
    OLLAMA_NUM_PREDICT: int = 700
    OLLAMA_NUM_CTX: int = 4096
    OLLAMA_TIMEOUT: int = 150

    # Google News RSS (busca gratuita, sem chave)
    NEWS_HL: str = 'pt-BR'
    NEWS_GL: str = 'BR'
    NEWS_CEID: str = 'BR:pt-BR'
    # Período padrão quando a busca não informa datas.
    NEWS_WINDOW_DAYS: int = Field(default=30, ge=1, le=MAX_PERIODO_DIAS)
    # Candidatos (já deduplicados) enviados ao modelo por empresa.
    NEWS_MAX_ITEMS: int = 30
    # Notícias no briefing final — o alvo pedido no prompt e o teto
    # aplicado na normalização.
    NEWS_TARGET_ITEMS: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
