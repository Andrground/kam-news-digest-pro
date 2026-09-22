from datetime import datetime, timedelta
from http import HTTPStatus
from zoneinfo import ZoneInfo

from jwt import encode

from kamnews.models import STATUS_INATIVO
from kamnews.settings import get_settings
from tests.conftest import KAM_PASSWORD, auth


def test_login(client, kam_user):
    response = client.post(
        '/auth/token',
        data={'username': kam_user.email, 'password': KAM_PASSWORD},
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['token_type'] == 'Bearer'
    assert body['access_token']


def test_login_wrong_password(client, kam_user):
    response = client.post(
        '/auth/token',
        data={'username': kam_user.email, 'password': 'errada'},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_login_unknown_email(client, kam_user):
    response = client.post(
        '/auth/token',
        data={'username': 'ninguem@teste.com', 'password': KAM_PASSWORD},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_login_inactive_user(client, session, kam_user):
    """Usuário inativo recebe a mesma mensagem — não vaza que existe."""
    kam_user.status = STATUS_INATIVO
    session.commit()

    response = client.post(
        '/auth/token',
        data={'username': kam_user.email, 'password': KAM_PASSWORD},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()['detail'] == 'Incorrect username or password'


def test_inactive_user_token_is_rejected(client, session, kam_user, kam_token):
    kam_user.status = STATUS_INATIVO
    session.commit()

    response = client.get('/users/me/', headers=auth(kam_token))
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_invalid_token(client, kam_user):
    response = client.get('/users/me/', headers=auth('nao-e-um-jwt'))
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_expired_token(client, kam_user):
    settings = get_settings()
    expired = encode(
        {
            'sub': kam_user.email,
            'exp': datetime.now(tz=ZoneInfo('UTC')) - timedelta(minutes=1),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    response = client.get('/users/me/', headers=auth(expired))
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_token_without_sub(client, kam_user):
    settings = get_settings()
    token = encode(
        {'exp': datetime.now(tz=ZoneInfo('UTC')) + timedelta(minutes=5)},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )

    response = client.get('/users/me/', headers=auth(token))
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_refresh_token(client, kam_token):
    response = client.post('/auth/refresh_token', headers=auth(kam_token))
    assert response.status_code == HTTPStatus.OK
    assert response.json()['access_token']
