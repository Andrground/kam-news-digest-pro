from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from kamnews.database import get_session
from kamnews.models import Carteira, KeyAccount, Role, User
from kamnews.schemas import (
    Message,
    UserList,
    UserPublic,
    UserSchema,
    UserUpdate,
)
from kamnews.security import (
    T_CurrentAdmin,
    T_CurrentUser,
    get_password_hash,
)

router = APIRouter(prefix='/users', tags=['users'])

T_Session = Annotated[Session, Depends(get_session)]

USER_NOT_FOUND = 'User not found'
ROLE_NOT_FOUND = 'Role not found'


def _check_duplicate(
    session: Session, username: str, email: str, user_id: int | None = None
) -> None:
    stmt = select(User).where(
        or_(User.username == username, User.email == email)
    )
    if user_id is not None:
        stmt = stmt.where(User.id != user_id)

    existing = session.scalar(stmt)
    if not existing:
        return

    detail = (
        'Username already exists'
        if existing.username == username
        else 'Email already exists'
    )
    raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=detail)


def _check_role(session: Session, role_id: int) -> None:
    if not session.scalar(select(Role).where(Role.id == role_id)):
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail=ROLE_NOT_FOUND
        )


def _get_user(session: Session, user_id: int) -> User:
    user = session.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail=USER_NOT_FOUND
        )
    return user


@router.get('/me/', response_model=UserPublic)
def read_current_user(current_user: T_CurrentUser):
    """Quem está logado e com qual papel — o frontend usa para decidir
    se mostra a aba Usuários."""
    return current_user


@router.get('/', response_model=UserList)
def read_users(
    session: T_Session,
    current_admin: T_CurrentAdmin,
    limit: int = 100,
    skip: int = 0,
):
    users = session.scalars(
        select(User).order_by(User.username).limit(limit).offset(skip)
    ).all()
    return {'users': users}


@router.post('/', status_code=HTTPStatus.CREATED, response_model=UserPublic)
def create_user(
    user: UserSchema, session: T_Session, current_admin: T_CurrentAdmin
):
    _check_duplicate(session, user.username, user.email)
    _check_role(session, user.role_id)

    db_user = User(
        username=user.username,
        email=user.email,
        password=get_password_hash(user.password),
        role_id=user.role_id,
        status=user.status,
    )
    session.add(db_user)
    session.commit()
    session.refresh(db_user)

    return db_user


@router.put('/{user_id}/', response_model=UserPublic)
def update_user(
    user_id: int,
    user: UserUpdate,
    session: T_Session,
    current_admin: T_CurrentAdmin,
):
    db_user = _get_user(session, user_id)
    _check_duplicate(session, user.username, user.email, user_id)
    _check_role(session, user.role_id)

    db_user.username = user.username
    db_user.email = user.email
    db_user.role_id = user.role_id
    db_user.status = user.status
    # Senha vazia = não alterar.
    if user.password:
        db_user.password = get_password_hash(user.password)

    session.commit()
    session.refresh(db_user)

    return db_user


@router.delete('/{user_id}/', response_model=Message)
def delete_user(
    user_id: int, session: T_Session, current_admin: T_CurrentAdmin
):
    db_user = _get_user(session, user_id)

    if db_user.id == current_admin.id:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail='Cannot delete yourself',
        )

    # As FKs owner_id não têm cascade de propósito: apagar um dono tem
    # de ser decisão explícita, não perda silenciosa de dados.
    has_data = session.scalar(
        select(Carteira.id).where(Carteira.owner_id == user_id)
    ) or session.scalar(
        select(KeyAccount.id).where(KeyAccount.owner_id == user_id)
    )
    if has_data:
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail='User has carteiras or key accounts',
        )

    session.delete(db_user)
    session.commit()

    return {'message': 'User deleted'}
