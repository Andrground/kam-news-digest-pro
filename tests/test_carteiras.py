from http import HTTPStatus

from sqlalchemy import select

from kamnews.models import STATUS_INATIVO, Carteira, carteira_key_account
from tests.conftest import auth


def test_create_carteira(client, kam_token, kam_user):
    response = client.post(
        '/carteiras/', json={'nome': 'Nova'}, headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body['nome'] == 'Nova'
    assert body['status'] == 'ativo'
    # owner_id vem do token, nunca do corpo.
    assert body['owner_id'] == kam_user.id


def test_create_carteira_ignores_owner_in_body(
    client, kam_token, kam_user, other_kam_user
):
    response = client.post(
        '/carteiras/',
        json={'nome': 'Nova', 'owner_id': other_kam_user.id},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.CREATED
    assert response.json()['owner_id'] == kam_user.id


def test_create_carteira_duplicate(client, kam_token, carteira):
    response = client.post(
        '/carteiras/', json={'nome': carteira.nome}, headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()['detail'] == 'Carteira name already exists'


def test_same_name_different_owners_is_allowed(
    client, kam_token, other_kam_token, carteira
):
    """A UniqueConstraint é (nome, owner_id), não só nome."""
    response = client.post(
        '/carteiras/',
        json={'nome': carteira.nome},
        headers=auth(other_kam_token),
    )
    assert response.status_code == HTTPStatus.CREATED


def test_create_carteira_invalid_status(client, kam_token):
    response = client.post(
        '/carteiras/',
        json={'nome': 'Nova', 'status': 'xpto'},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_read_carteiras(client, kam_token, carteira):
    response = client.get('/carteiras/', headers=auth(kam_token))
    assert response.status_code == HTTPStatus.OK
    nomes = [c['nome'] for c in response.json()['carteiras']]
    assert nomes == [carteira.nome]


def test_read_carteiras_requires_token(client):
    response = client.get('/carteiras/')
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_read_carteiras_filter_status(client, kam_token, carteira, session):
    carteira.status = STATUS_INATIVO
    session.commit()

    ativas = client.get('/carteiras/?status=ativo', headers=auth(kam_token))
    assert ativas.json()['carteiras'] == []

    inativas = client.get(
        '/carteiras/?status=inativo', headers=auth(kam_token)
    )
    assert len(inativas.json()['carteiras']) == 1


def test_kam_does_not_see_other_carteiras(client, other_kam_token, carteira):
    response = client.get('/carteiras/', headers=auth(other_kam_token))
    assert response.json()['carteiras'] == []

    assert (
        client.get(
            f'/carteiras/{carteira.id}/', headers=auth(other_kam_token)
        ).status_code
        == HTTPStatus.NOT_FOUND
    )


def test_admin_sees_and_edits_carteira_of_kam(client, admin_token, carteira):
    response = client.get('/carteiras/', headers=auth(admin_token))
    assert len(response.json()['carteiras']) == 1

    response = client.put(
        f'/carteiras/{carteira.id}/',
        json={'nome': 'Renomeada pelo admin'},
        headers=auth(admin_token),
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['nome'] == 'Renomeada pelo admin'


def test_read_carteira_not_found(client, kam_token):
    response = client.get('/carteiras/9999/', headers=auth(kam_token))
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_update_carteira(client, kam_token, carteira):
    response = client.put(
        f'/carteiras/{carteira.id}/',
        json={'nome': 'Outro nome', 'status': 'inativo'},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['nome'] == 'Outro nome'
    assert body['status'] == 'inativo'


def test_update_carteira_duplicate_name(
    client, kam_token, kam_user, carteira, session
):
    outra = Carteira(nome='Outra', owner_id=kam_user.id)
    session.add(outra)
    session.commit()
    session.refresh(outra)

    response = client.put(
        f'/carteiras/{outra.id}/',
        json={'nome': carteira.nome},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_update_carteira_same_name_is_allowed(client, kam_token, carteira):
    """Renomear para o próprio nome não pode colidir consigo mesma."""
    response = client.put(
        f'/carteiras/{carteira.id}/',
        json={'nome': carteira.nome, 'status': 'inativo'},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.OK


def test_update_carteira_not_found(client, kam_token):
    response = client.put(
        '/carteiras/9999/', json={'nome': 'X'}, headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_delete_carteira(client, kam_token, carteira):
    response = client.delete(
        f'/carteiras/{carteira.id}/', headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {'message': 'Carteira deleted'}


def test_delete_carteira_not_found(client, kam_token):
    response = client.delete('/carteiras/9999/', headers=auth(kam_token))
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_delete_carteira_clears_link_but_keeps_key_account(
    client, kam_token, carteira_com_ka, key_account, session
):
    response = client.delete(
        f'/carteiras/{carteira_com_ka.id}/', headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.OK

    assert session.execute(select(carteira_key_account)).all() == []
    assert (
        client.get(
            f'/key-accounts/{key_account.id}/', headers=auth(kam_token)
        ).status_code
        == HTTPStatus.OK
    )
