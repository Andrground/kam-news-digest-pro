from http import HTTPStatus

from sqlalchemy import select

from kamnews.models import (
    STATUS_INATIVO,
    Carteira,
    KeyAccount,
    carteira_key_account,
)
from tests.conftest import auth


def test_create_key_account(client, kam_token, kam_user):
    response = client.post(
        '/key-accounts/', json={'nome': 'Embraer'}, headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body['nome'] == 'Embraer'
    assert body['owner_id'] == kam_user.id


def test_create_key_account_duplicate(client, kam_token, key_account):
    response = client.post(
        '/key-accounts/',
        json={'nome': key_account.nome},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()['detail'] == 'Key account name already exists'


def test_same_name_different_owners_is_allowed(
    client, other_kam_token, key_account
):
    response = client.post(
        '/key-accounts/',
        json={'nome': key_account.nome},
        headers=auth(other_kam_token),
    )
    assert response.status_code == HTTPStatus.CREATED


def test_create_key_account_invalid_status(client, kam_token):
    response = client.post(
        '/key-accounts/',
        json={'nome': 'Embraer', 'status': 'xpto'},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_read_key_accounts(client, kam_token, key_account):
    response = client.get('/key-accounts/', headers=auth(kam_token))
    assert response.status_code == HTTPStatus.OK
    nomes = [k['nome'] for k in response.json()['key_accounts']]
    assert nomes == [key_account.nome]


def test_read_key_accounts_requires_token(client):
    response = client.get('/key-accounts/')
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_read_key_accounts_filter_status(
    client, kam_token, key_account, session
):
    key_account.status = STATUS_INATIVO
    session.commit()

    ativas = client.get('/key-accounts/?status=ativo', headers=auth(kam_token))
    assert ativas.json()['key_accounts'] == []

    inativas = client.get(
        '/key-accounts/?status=inativo', headers=auth(kam_token)
    )
    assert len(inativas.json()['key_accounts']) == 1


def test_kam_does_not_see_other_key_accounts(
    client, other_kam_token, key_account
):
    response = client.get('/key-accounts/', headers=auth(other_kam_token))
    assert response.json()['key_accounts'] == []

    assert (
        client.get(
            f'/key-accounts/{key_account.id}/', headers=auth(other_kam_token)
        ).status_code
        == HTTPStatus.NOT_FOUND
    )


def test_admin_sees_key_account_of_kam(client, admin_token, key_account):
    response = client.get('/key-accounts/', headers=auth(admin_token))
    assert len(response.json()['key_accounts']) == 1


def test_read_key_account_not_found(client, kam_token):
    response = client.get('/key-accounts/9999/', headers=auth(kam_token))
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_update_key_account(client, kam_token, key_account):
    response = client.put(
        f'/key-accounts/{key_account.id}/',
        json={'nome': 'Vale S.A.', 'status': 'inativo'},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['nome'] == 'Vale S.A.'
    assert body['status'] == 'inativo'


def test_update_key_account_duplicate_name(
    client, kam_token, kam_user, key_account, session
):
    outra = KeyAccount(nome='Gerdau', owner_id=kam_user.id)
    session.add(outra)
    session.commit()
    session.refresh(outra)

    response = client.put(
        f'/key-accounts/{outra.id}/',
        json={'nome': key_account.nome},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_update_key_account_not_found(client, kam_token):
    response = client.put(
        '/key-accounts/9999/', json={'nome': 'X'}, headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_delete_key_account(client, kam_token, key_account):
    response = client.delete(
        f'/key-accounts/{key_account.id}/', headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {'message': 'Key account deleted'}


def test_delete_key_account_not_found(client, kam_token):
    response = client.delete('/key-accounts/9999/', headers=auth(kam_token))
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_delete_key_account_clears_link_but_keeps_carteira(
    client, kam_token, carteira_com_ka, key_account, session
):
    response = client.delete(
        f'/key-accounts/{key_account.id}/', headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.OK

    assert session.execute(select(carteira_key_account)).all() == []
    carteira = session.scalar(
        select(Carteira).where(Carteira.id == carteira_com_ka.id)
    )
    assert carteira is not None
    assert carteira.key_accounts == []
