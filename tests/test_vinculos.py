from http import HTTPStatus

from kamnews.models import STATUS_INATIVO, KeyAccount
from tests.conftest import auth


def _link_url(carteira_id, key_account_id):
    return f'/carteiras/{carteira_id}/key-accounts/{key_account_id}/'


def test_link(client, kam_token, carteira, key_account):
    response = client.post(
        _link_url(carteira.id, key_account.id), headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.OK
    nomes = [k['nome'] for k in response.json()['key_accounts']]
    assert nomes == [key_account.nome]


def test_link_is_idempotent(client, kam_token, carteira, key_account):
    """O chip alterna: um duplo clique não pode virar erro."""
    url = _link_url(carteira.id, key_account.id)

    first = client.post(url, headers=auth(kam_token))
    second = client.post(url, headers=auth(kam_token))

    assert first.status_code == HTTPStatus.OK
    assert second.status_code == HTTPStatus.OK
    assert len(second.json()['key_accounts']) == 1


def test_unlink(client, kam_token, carteira_com_ka, key_account):
    response = client.delete(
        _link_url(carteira_com_ka.id, key_account.id),
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['key_accounts'] == []


def test_unlink_is_idempotent(client, kam_token, carteira, key_account):
    url = _link_url(carteira.id, key_account.id)

    first = client.delete(url, headers=auth(kam_token))
    second = client.delete(url, headers=auth(kam_token))

    assert first.status_code == HTTPStatus.OK
    assert second.status_code == HTTPStatus.OK
    assert second.json()['key_accounts'] == []


def test_link_unknown_carteira(client, kam_token, key_account):
    response = client.post(
        _link_url(9999, key_account.id), headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()['detail'] == 'Carteira not found'


def test_link_unknown_key_account(client, kam_token, carteira):
    response = client.post(
        _link_url(carteira.id, 9999), headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()['detail'] == 'Key account not found'


def test_link_key_account_of_other_owner(
    client, kam_token, carteira, other_kam_user, session
):
    alheia = KeyAccount(nome='Alheia', owner_id=other_kam_user.id)
    session.add(alheia)
    session.commit()
    session.refresh(alheia)

    response = client.post(
        _link_url(carteira.id, alheia.id), headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_link_carteira_of_other_owner(
    client, other_kam_token, carteira, key_account
):
    response = client.post(
        _link_url(carteira.id, key_account.id),
        headers=auth(other_kam_token),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_link_inactive_key_account_is_allowed(
    client, kam_token, carteira, key_account, session
):
    """Só o /portfolios/ filtra por status; o cadastro não."""
    key_account.status = STATUS_INATIVO
    session.commit()

    response = client.post(
        _link_url(carteira.id, key_account.id), headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.OK
    assert len(response.json()['key_accounts']) == 1
