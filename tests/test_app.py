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
