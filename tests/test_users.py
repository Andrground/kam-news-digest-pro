from http import HTTPStatus

from kamnews.models import ROLE_ADMIN, ROLE_KAM
from tests.conftest import KAM_PASSWORD, auth


def test_read_me_as_kam(client, kam_token, kam_user):
    response = client.get('/users/me/', headers=auth(kam_token))
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['username'] == kam_user.username
    assert body['role']['nome'] == ROLE_KAM
    assert 'password' not in body


def test_read_me_as_admin(client, admin_token):
    response = client.get('/users/me/', headers=auth(admin_token))
    assert response.status_code == HTTPStatus.OK
    assert response.json()['role']['nome'] == ROLE_ADMIN


def test_read_users_as_admin(client, admin_token, kam_user):
    response = client.get('/users/', headers=auth(admin_token))
    assert response.status_code == HTTPStatus.OK
    usernames = [u['username'] for u in response.json()['users']]
    assert kam_user.username in usernames


def test_read_users_as_kam_is_forbidden(client, kam_token):
    response = client.get('/users/', headers=auth(kam_token))
    assert response.status_code == HTTPStatus.FORBIDDEN


def test_create_user(client, admin_token, role_kam):
    response = client.post(
        '/users/',
        json={
            'username': 'novo',
            'email': 'novo@teste.com',
            'password': 'segredo',
            'role_id': role_kam.id,
        },
        headers=auth(admin_token),
    )
    assert response.status_code == HTTPStatus.CREATED
    assert response.json()['username'] == 'novo'


def test_create_user_as_kam_is_forbidden(client, kam_token, role_kam):
    response = client.post(
        '/users/',
        json={
            'username': 'novo',
            'email': 'novo@teste.com',
            'password': 'segredo',
            'role_id': role_kam.id,
        },
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.FORBIDDEN


def test_create_user_duplicate_username(
    client, admin_token, role_kam, kam_user
):
    response = client.post(
        '/users/',
        json={
            'username': kam_user.username,
            'email': 'outro@teste.com',
            'password': 'segredo',
            'role_id': role_kam.id,
        },
        headers=auth(admin_token),
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()['detail'] == 'Username already exists'


def test_create_user_duplicate_email(client, admin_token, role_kam, kam_user):
    response = client.post(
        '/users/',
        json={
            'username': 'outro',
            'email': kam_user.email,
            'password': 'segredo',
            'role_id': role_kam.id,
        },
        headers=auth(admin_token),
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()['detail'] == 'Email already exists'


def test_create_user_unknown_role(client, admin_token, role_admin):
    response = client.post(
        '/users/',
        json={
            'username': 'novo',
            'email': 'novo@teste.com',
            'password': 'segredo',
            'role_id': 9999,
        },
        headers=auth(admin_token),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()['detail'] == 'Role not found'


def test_create_user_invalid_status(client, admin_token, role_kam):
    response = client.post(
        '/users/',
        json={
            'username': 'novo',
            'email': 'novo@teste.com',
            'password': 'segredo',
            'role_id': role_kam.id,
            'status': 'xpto',
        },
        headers=auth(admin_token),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_update_user_keeps_password_when_blank(
    client, admin_token, kam_user, role_kam
):
    """Editar sem informar senha não pode invalidar o login antigo."""
    response = client.put(
        f'/users/{kam_user.id}/',
        json={
            'username': 'mayra-renomeada',
            'email': kam_user.email,
            'role_id': role_kam.id,
        },
        headers=auth(admin_token),
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['username'] == 'mayra-renomeada'

    login = client.post(
        '/auth/token',
        data={'username': kam_user.email, 'password': KAM_PASSWORD},
    )
    assert login.status_code == HTTPStatus.OK


def test_update_user_changes_password(client, admin_token, kam_user, role_kam):
    response = client.put(
        f'/users/{kam_user.id}/',
        json={
            'username': kam_user.username,
            'email': kam_user.email,
            'password': 'nova-senha',
            'role_id': role_kam.id,
        },
        headers=auth(admin_token),
    )
    assert response.status_code == HTTPStatus.OK

    assert (
        client.post(
            '/auth/token',
            data={'username': kam_user.email, 'password': KAM_PASSWORD},
        ).status_code
        == HTTPStatus.BAD_REQUEST
    )
    assert (
        client.post(
            '/auth/token',
            data={'username': kam_user.email, 'password': 'nova-senha'},
        ).status_code
        == HTTPStatus.OK
    )


def test_update_user_not_found(client, admin_token, role_kam):
    response = client.put(
        '/users/9999/',
        json={
            'username': 'x',
            'email': 'x@teste.com',
            'role_id': role_kam.id,
        },
        headers=auth(admin_token),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_update_user_duplicate(
    client, admin_token, kam_user, other_kam_user, role_kam
):
    response = client.put(
        f'/users/{kam_user.id}/',
        json={
            'username': other_kam_user.username,
            'email': kam_user.email,
            'role_id': role_kam.id,
        },
        headers=auth(admin_token),
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_delete_user(client, admin_token, kam_user):
    response = client.delete(
        f'/users/{kam_user.id}/', headers=auth(admin_token)
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {'message': 'User deleted'}


def test_delete_user_not_found(client, admin_token):
    response = client.delete('/users/9999/', headers=auth(admin_token))
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_delete_yourself_is_rejected(client, admin_token, admin_user):
    response = client.delete(
        f'/users/{admin_user.id}/', headers=auth(admin_token)
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()['detail'] == 'Cannot delete yourself'


def test_delete_user_with_carteira_is_rejected(
    client, admin_token, kam_user, carteira
):
    response = client.delete(
        f'/users/{kam_user.id}/', headers=auth(admin_token)
    )
    assert response.status_code == HTTPStatus.CONFLICT


def test_delete_user_with_key_account_is_rejected(
    client, admin_token, kam_user, key_account
):
    response = client.delete(
        f'/users/{kam_user.id}/', headers=auth(admin_token)
    )
    assert response.status_code == HTTPStatus.CONFLICT


def test_read_roles(client, admin_token, role_admin, role_kam):
    response = client.get('/roles/', headers=auth(admin_token))
    assert response.status_code == HTTPStatus.OK
    nomes = [r['nome'] for r in response.json()['roles']]
    assert set(nomes) == {ROLE_ADMIN, ROLE_KAM}


def test_read_roles_as_kam_is_forbidden(client, kam_token):
    response = client.get('/roles/', headers=auth(kam_token))
    assert response.status_code == HTTPStatus.FORBIDDEN
