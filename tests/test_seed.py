from http import HTTPStatus

from sqlalchemy import func, select

from kamnews.models import Carteira, KeyAccount, Role, User
from kamnews.portfolios import PORTFOLIOS
from kamnews.security import verify_password
from kamnews.seed import seed_session, slugify
from kamnews.settings import get_settings

EXPECTED_ROLES = 2


def _count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_slugify_removes_accents():
    assert slugify('Rogério') == 'rogerio'
    assert slugify('Mayra') == 'mayra'


def test_seed_creates_roles_users_and_carteiras(session):
    seed_session(session)

    assert _count(session, Role) == EXPECTED_ROLES
    # 1 admin + 1 KAM por carteira.
    assert _count(session, User) == len(PORTFOLIOS) + 1
    assert _count(session, Carteira) == len(PORTFOLIOS)

    total_empresas = sum(len(e) for e in PORTFOLIOS.values())
    assert _count(session, KeyAccount) == total_empresas


def _kam_email(nome):
    return f'{slugify(nome)}@{get_settings().SEED_EMAIL_DOMAIN}'


def test_seeded_emails_are_serializable(client, seeded):
    """Regressão: um domínio de uso especial (.local, .internal) passa no
    banco mas explode no EmailStr do UserPublic, quebrando /users/me/."""
    response = client.post(
        '/auth/token',
        data={
            'username': _kam_email('Mayra'),
            'password': get_settings().SEED_KAM_PASSWORD,
        },
    )
    assert response.status_code == HTTPStatus.OK
    token = response.json()['access_token']

    me = client.get('/users/me/', headers={'Authorization': f'Bearer {token}'})
    assert me.status_code == HTTPStatus.OK
    assert me.json()['email'] == _kam_email('Mayra')


def test_seed_assigns_carteira_to_its_own_kam(session):
    seed_session(session)

    for nome, empresas in PORTFOLIOS.items():
        kam = session.scalar(
            select(User).where(User.email == _kam_email(nome))
        )
        assert kam is not None

        carteira = session.scalar(
            select(Carteira).where(Carteira.nome == nome)
        )
        assert carteira.owner_id == kam.id
        assert sorted(k.nome for k in carteira.key_accounts) == sorted(
            empresas
        )
        assert all(k.owner_id == kam.id for k in carteira.key_accounts)


def test_seed_is_idempotent(session):
    seed_session(session)
    counts = (
        _count(session, Role),
        _count(session, User),
        _count(session, Carteira),
        _count(session, KeyAccount),
    )

    seed_session(session)

    assert (
        _count(session, Role),
        _count(session, User),
        _count(session, Carteira),
        _count(session, KeyAccount),
    ) == counts

    # Sem vínculo duplicado (a PK composta impediria, mas o append
    # cego levantaria erro antes de chegar lá).
    carteira = session.scalar(select(Carteira).where(Carteira.nome == 'Mayra'))
    assert len(carteira.key_accounts) == len(PORTFOLIOS['Mayra'])


def test_seed_does_not_reset_existing_password(session):
    seed_session(session)

    settings = get_settings()
    admin = session.scalar(
        select(User).where(User.email == settings.MASTER_EMAIL)
    )
    admin.password = 'hash-trocado-a-mao'
    session.commit()

    seed_session(session)

    session.refresh(admin)
    assert admin.password == 'hash-trocado-a-mao'


def test_seed_hashes_passwords(session):
    seed_session(session)

    settings = get_settings()
    admin = session.scalar(
        select(User).where(User.email == settings.MASTER_EMAIL)
    )
    assert admin.password != settings.MASTER_PASSWORD
    assert verify_password(settings.MASTER_PASSWORD, admin.password)
