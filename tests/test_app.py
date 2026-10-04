from http import HTTPStatus


def test_health(client):
    response = client.get('/health')
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {'message': 'ok'}


def test_index_html_served(client):
    response = client.get('/')
    assert response.status_code == HTTPStatus.OK
    assert 'text/html' in response.headers['content-type']
    assert 'KAM News Digest' in response.text


def test_index_html_nao_e_cacheado(client):
    """Sem isto o navegador roda JS antigo contra a API nova, e a
    interface parece não ter o que já está no servidor."""
    response = client.get('/')
    assert response.headers['cache-control'] == 'no-cache'


def test_json_nao_ganha_cache_control(client):
    response = client.get('/health')
    assert 'cache-control' not in response.headers
