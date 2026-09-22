from http import HTTPStatus

from kamnews.app import app
from kamnews.news_service import NewsServiceError
from kamnews.routers.news import get_news_fetcher
from tests.conftest import auth


def test_search_news(client, fake_news, kam_token):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    response = client.post(
        '/news/',
        json={'company': 'Vale', 'date_str': 'hoje'},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['empresa'] == 'Vale'
    assert body['temNoticias'] is True
    assert body['temas'][0]['categoria'] == 'm_a'


def test_search_news_empty_company(client, fake_news, kam_token):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    response = client.post(
        '/news/', json={'company': '   '}, headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_search_news_service_error(client, kam_token):
    async def _boom(company, date_str):
        raise NewsServiceError('Falha simulada.')

    app.dependency_overrides[get_news_fetcher] = lambda: _boom
    response = client.post(
        '/news/', json={'company': 'Vale'}, headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.BAD_GATEWAY
    assert response.json()['detail'] == 'Falha simulada.'


def test_search_news_requires_token(client, fake_news):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    response = client.post('/news/', json={'company': 'Vale'})
    assert response.status_code == HTTPStatus.UNAUTHORIZED
