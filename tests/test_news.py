from datetime import timedelta
from http import HTTPStatus

import pytest

from kamnews.app import app
from kamnews.news_service import NewsServiceError
from kamnews.routers.news import get_news_fetcher
from kamnews.settings import MAX_PERIODO_DIAS, get_settings, hoje_br
from tests.conftest import auth


def test_search_news(client, fake_news, kam_token, key_account):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    response = client.post(
        '/news/',
        json={'company': key_account.nome, 'date_str': 'hoje'},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['empresa'] == key_account.nome
    assert body['temNoticias'] is True
    assert body['temas'][0]['categoria'] == 'm_a'


def test_search_news_empty_company(client, fake_news, kam_token):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    response = client.post(
        '/news/', json={'company': '   '}, headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_search_news_service_error(client, kam_token, key_account):
    async def _boom(company, date_str, periodo):
        raise NewsServiceError('Falha simulada.')

    app.dependency_overrides[get_news_fetcher] = lambda: _boom
    response = client.post(
        '/news/',
        json={'company': key_account.nome},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.BAD_GATEWAY
    assert response.json()['detail'] == 'Falha simulada.'


def test_search_news_requires_token(client, fake_news):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    response = client.post('/news/', json={'company': 'Vale'})
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_search_news_unknown_company(client, fake_news, kam_token):
    """Sem key account cadastrada não há onde pendurar o histórico."""
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    response = client.post(
        '/news/',
        json={'company': 'Empresa Que Nao Existe'},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_search_news_key_account_of_other_owner(
    client, fake_news, other_kam_token, key_account
):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    response = client.post(
        '/news/',
        json={
            'company': key_account.nome,
            'key_account_id': key_account.id,
        },
        headers=auth(other_kam_token),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_search_news_by_key_account_id(
    client, fake_news, kam_token, key_account
):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    response = client.post(
        '/news/',
        json={
            'company': key_account.nome,
            'key_account_id': key_account.id,
        },
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['temas'][0]['itens'][0]['id'] is not None


def _capturar_periodo(fake_news, recebido):
    async def _fake(company, date_str, periodo):
        recebido.append(periodo)
        return await fake_news(company, date_str, periodo)

    return _fake


def test_search_news_repassa_o_periodo(
    client, fake_news, kam_token, key_account
):
    recebido = []
    app.dependency_overrides[get_news_fetcher] = lambda: _capturar_periodo(
        fake_news, recebido
    )
    hoje = hoje_br()
    inicio = hoje - timedelta(days=MAX_PERIODO_DIAS)
    response = client.post(
        '/news/',
        json={
            'company': key_account.nome,
            'data_inicio': inicio.isoformat(),
            'data_fim': hoje.isoformat(),
        },
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.OK
    assert recebido == [(inicio, hoje)]


def test_search_news_sem_periodo_usa_o_padrao(
    client, fake_news, kam_token, key_account
):
    recebido = []
    app.dependency_overrides[get_news_fetcher] = lambda: _capturar_periodo(
        fake_news, recebido
    )
    response = client.post(
        '/news/', json={'company': key_account.nome}, headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.OK
    hoje = hoje_br()
    dias = get_settings().NEWS_WINDOW_DAYS
    assert recebido == [(hoje - timedelta(days=dias), hoje)]


@pytest.mark.parametrize(
    'dias_atras',
    [
        # Além do limite de 60 dias.
        (MAX_PERIODO_DIAS + 1, 0),
        # Data final no futuro.
        (7, -1),
        # Início depois do fim.
        (3, 5),
    ],
)
def test_search_news_periodo_invalido(
    client, fake_news, kam_token, key_account, dias_atras
):
    """`dias_atras` = (início, fim) contados para trás a partir de hoje."""
    inicio, fim = dias_atras
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    hoje = hoje_br()
    response = client.post(
        '/news/',
        json={
            'company': key_account.nome,
            'data_inicio': (hoje - timedelta(days=inicio)).isoformat(),
            'data_fim': (hoje - timedelta(days=fim)).isoformat(),
        },
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
