from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Valor de SECRET_KEY que indica ambiente de desenvolvimento. O
# bootstrap avisa quando detecta este valor — em produção, gere um novo
# com `openssl rand -hex 32`.
DEV_SECRET_KEY = 'dev-only-trocar-em-producao'


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
    NEWS_WINDOW_DAYS: int = 30
    # Candidatos (já deduplicados) enviados ao modelo por empresa.
    NEWS_MAX_ITEMS: int = 30
    # Notícias no briefing final — o alvo pedido no prompt e o teto
    # aplicado na normalização.
    NEWS_TARGET_ITEMS: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
