import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

from kamnews.app import app
from kamnews.database import get_session
from kamnews.models import (
    ROLE_ADMIN,
    ROLE_KAM,
    Carteira,
    KeyAccount,
    Role,
    User,
    table_registry,
)
from kamnews.security import get_password_hash
from kamnews.seed import seed_session

ADMIN_PASSWORD = 'admin123'
KAM_PASSWORD = 'kam123'


@pytest.fixture(scope='session')
def engine():
    with PostgresContainer('postgres:16', driver='psycopg') as postgres:
        _engine = create_engine(postgres.get_connection_url())
        with _engine.begin():
            yield _engine


@pytest.fixture
def session(engine):
    table_registry.metadata.create_all(engine)

    with Session(engine) as session:
        yield session
        session.rollback()

    table_registry.metadata.drop_all(engine)


@pytest.fixture
def client(session):
    def get_session_override():
        return session

    with TestClient(app) as test_client:
        app.dependency_overrides[get_session] = get_session_override

        yield test_client

    app.dependency_overrides.clear()


# --------------------------------------------------------------------- #
# Papéis e usuários
# --------------------------------------------------------------------- #
def _add_role(session, nome):
    # Get-or-create: o `seeded` também cria os papéis, e as fixtures
    # precisam poder ser compostas em qualquer ordem.
    role = session.scalar(select(Role).where(Role.nome == nome))
    if role:
        return role

    role = Role(nome=nome)
    session.add(role)
    session.commit()
    session.refresh(role)
    return role


def _add_user(session, username, email, password, role):
    user = User(
        username=username,
        email=email,
        password=get_password_hash(password),
        role_id=role.id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    user.clean_password = password
    return user


def _token(client, user):
    response = client.post(
        '/auth/token',
        data={'username': user.email, 'password': user.clean_password},
    )
    return response.json()['access_token']


def auth(token):
    """Header pronto para os testes de rota."""
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def role_admin(session):
    return _add_role(session, ROLE_ADMIN)


@pytest.fixture
def role_kam(session):
    return _add_role(session, ROLE_KAM)


@pytest.fixture
def admin_user(session, role_admin):
    # Distinto do 'master' criado pelo seed: as duas fixtures podem
    # coexistir no mesmo teste.
    return _add_user(
        session, 'admin-teste', 'admin@teste.com', ADMIN_PASSWORD, role_admin
    )


@pytest.fixture
def kam_user(session, role_kam):
    return _add_user(
        session, 'mayra', 'mayra@teste.com', KAM_PASSWORD, role_kam
    )


@pytest.fixture
def other_kam_user(session, role_kam):
    return _add_user(
        session, 'renata', 'renata@teste.com', KAM_PASSWORD, role_kam
    )


@pytest.fixture
def admin_token(client, admin_user):
    return _token(client, admin_user)


@pytest.fixture
def kam_token(client, kam_user):
    return _token(client, kam_user)


@pytest.fixture
def other_kam_token(client, other_kam_user):
    return _token(client, other_kam_user)


# --------------------------------------------------------------------- #
# Domínio
# --------------------------------------------------------------------- #
@pytest.fixture
def carteira(session, kam_user):
    carteira = Carteira(nome='Carteira Mayra', owner_id=kam_user.id)
    session.add(carteira)
    session.commit()
    session.refresh(carteira)
    return carteira


@pytest.fixture
def key_account(session, kam_user):
    key_account = KeyAccount(nome='Vale', owner_id=kam_user.id)
    session.add(key_account)
    session.commit()
    session.refresh(key_account)
    return key_account


@pytest.fixture
def carteira_com_ka(session, carteira, key_account):
    carteira.key_accounts.append(key_account)
    session.commit()
    session.refresh(carteira)
    return carteira


@pytest.fixture
def seeded(session):
    seed_session(session)


@pytest.fixture
def fake_news():
    async def _fake(company, date_str, periodo):
        return {
            'empresa': company,
            'temNoticias': True,
            'manchetePrincipal': f'{company} teve novidades relevantes.',
            'resumo': 'Resumo de teste.',
            'temas': [
                {
                    'categoria': 'm_a',
                    'itens': [
                        {
                            'texto': 'Aquisição concluída.',
                            'fonte': 'Valor',
                            'data': '2026-01-01',
                            'url': 'https://exemplo.com',
                        }
                    ],
                }
            ],
        }

    return _fake
