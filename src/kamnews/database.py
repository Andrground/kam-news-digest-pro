from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from kamnews.settings import get_settings

# create_engine() não abre conexão: importar o app continua funcionando
# sem Postgres no ar (é o que mantém /health, / e os testes de RSS e
# summary offline).
engine = create_engine(get_settings().DATABASE_URL)


def get_session():  # pragma: no cover
    with Session(engine) as session:
        yield session
