from http import HTTPStatus

from sqlalchemy import select

from kamnews.models import STATUS_INATIVO, Carteira, KeyAccount
from kamnews.portfolios import PORTFOLIOS
from kamnews.settings import get_settings
from tests.conftest import auth


def test_read_portfolios(client, seeded, admin_token):
    """Prova que seed + models + shim concordam com a fonte hardcoded."""
    response = client.get('/portfolios/', headers=auth(admin_token))
    assert response.status_code == HTTPStatus.OK
    names = [p['name'] for p in response.json()['portfolios']]
    assert set(names) == set(PORTFOLIOS)


def test_read_portfolio(client, seeded, admin_token):
    response = client.get('/portfolios/Mayra/', headers=auth(admin_token))
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['name'] == 'Mayra'
    # A ordem agora é alfabética, então compara ordenado dos dois lados.
    assert sorted(body['companies']) == sorted(PORTFOLIOS['Mayra'])


def test_portfolio_traz_key_accounts_com_id(client, seeded, admin_token):
    """O frontend precisa do id para mandar no POST /news/ — o nome
    sozinho é ambíguo para o admin."""
    response = client.get('/portfolios/Mayra/', headers=auth(admin_token))
    assert response.status_code == HTTPStatus.OK
    body = response.json()

    nomes = [k['nome'] for k in body['key_accounts']]
    assert nomes == body['companies']
    assert all(isinstance(k['id'], int) for k in body['key_accounts'])


def test_read_portfolio_not_found(client, admin_token):
    response = client.get(
        '/portfolios/Inexistente/', headers=auth(admin_token)
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_read_portfolios_requires_token(client):
    response = client.get('/portfolios/')
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_kam_sees_only_own_portfolio(client, seeded, session):
    """Cada KAM enxerga só a carteira dele."""
    settings = get_settings()
    response = client.post(
        '/auth/token',
        data={
            'username': f'mayra@{settings.SEED_EMAIL_DOMAIN}',
            'password': settings.SEED_KAM_PASSWORD,
        },
    )
    assert response.status_code == HTTPStatus.OK
    token = response.json()['access_token']

    response = client.get('/portfolios/', headers=auth(token))
    assert response.status_code == HTTPStatus.OK
    names = [p['name'] for p in response.json()['portfolios']]
    assert names == ['Mayra']

    assert (
        client.get('/portfolios/Renata/', headers=auth(token)).status_code
        == HTTPStatus.NOT_FOUND
    )


def test_carteira_inativa_some(client, seeded, session, admin_token):
    carteira = session.scalar(select(Carteira).where(Carteira.nome == 'Mayra'))
    carteira.status = STATUS_INATIVO
    session.commit()

    response = client.get('/portfolios/', headers=auth(admin_token))
    names = [p['name'] for p in response.json()['portfolios']]
    assert 'Mayra' not in names

    assert (
        client.get('/portfolios/Mayra/', headers=auth(admin_token)).status_code
        == HTTPStatus.NOT_FOUND
    )


def test_key_account_inativa_some(client, seeded, session, admin_token):
    alvo = PORTFOLIOS['Mayra'][0]
    key_account = session.scalar(
        select(KeyAccount).where(KeyAccount.nome == alvo)
    )
    key_account.status = STATUS_INATIVO
    session.commit()

    response = client.get('/portfolios/Mayra/', headers=auth(admin_token))
    assert response.status_code == HTTPStatus.OK
    assert alvo not in response.json()['companies']
