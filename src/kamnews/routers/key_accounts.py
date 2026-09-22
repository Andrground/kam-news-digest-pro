from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from kamnews.database import get_session
from kamnews.models import KeyAccount, User
from kamnews.schemas import (
    KeyAccountList,
    KeyAccountPublic,
    KeyAccountSchema,
    Message,
    StatusLiteral,
)
from kamnews.security import T_CurrentUser, is_admin

router = APIRouter(prefix='/key-accounts', tags=['key-accounts'])

T_Session = Annotated[Session, Depends(get_session)]

NOT_FOUND = 'Key account not found'
DUPLICATE = 'Key account name already exists'


def scope(stmt, user: User):
    """Admin vê tudo; KAM vê só o que é dele."""
    if is_admin(user):
        return stmt
    return stmt.where(KeyAccount.owner_id == user.id)


def get_scoped(session: Session, key_account_id: int, user: User):
    """404 (e não 403) fora do escopo: não vaza ids alheios."""
    key_account = session.scalar(
        scope(select(KeyAccount).where(KeyAccount.id == key_account_id), user)
    )
    if not key_account:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=NOT_FOUND)
    return key_account


def _check_duplicate(
    session: Session,
    nome: str,
    owner_id: int,
    key_account_id: int | None = None,
) -> None:
    stmt = select(KeyAccount).where(
        KeyAccount.nome == nome, KeyAccount.owner_id == owner_id
    )
    if key_account_id is not None:
        stmt = stmt.where(KeyAccount.id != key_account_id)

    if session.scalar(stmt):
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail=DUPLICATE
        )


@router.get('/', response_model=KeyAccountList)
def read_key_accounts(
    session: T_Session,
    current_user: T_CurrentUser,
    status: StatusLiteral | None = None,
    limit: int = 100,
    skip: int = 0,
):
    stmt = scope(select(KeyAccount), current_user)
    if status:
        stmt = stmt.where(KeyAccount.status == status)

    key_accounts = session.scalars(
        stmt.order_by(KeyAccount.nome).limit(limit).offset(skip)
    ).all()
    return {'key_accounts': key_accounts}


@router.get('/{key_account_id}/', response_model=KeyAccountPublic)
def read_key_account(
    key_account_id: int, session: T_Session, current_user: T_CurrentUser
):
    return get_scoped(session, key_account_id, current_user)


@router.post(
    '/', status_code=HTTPStatus.CREATED, response_model=KeyAccountPublic
)
def create_key_account(
    key_account: KeyAccountSchema,
    session: T_Session,
    current_user: T_CurrentUser,
):
    _check_duplicate(session, key_account.nome, current_user.id)

    db_key_account = KeyAccount(
        nome=key_account.nome,
        owner_id=current_user.id,
        status=key_account.status,
    )
    session.add(db_key_account)
    session.commit()
    session.refresh(db_key_account)

    return db_key_account


@router.put('/{key_account_id}/', response_model=KeyAccountPublic)
def update_key_account(
    key_account_id: int,
    key_account: KeyAccountSchema,
    session: T_Session,
    current_user: T_CurrentUser,
):
    db_key_account = get_scoped(session, key_account_id, current_user)
    _check_duplicate(
        session, key_account.nome, db_key_account.owner_id, key_account_id
    )

    db_key_account.nome = key_account.nome
    db_key_account.status = key_account.status

    session.commit()
    session.refresh(db_key_account)

    return db_key_account


@router.delete('/{key_account_id}/', response_model=Message)
def delete_key_account(
    key_account_id: int, session: T_Session, current_user: T_CurrentUser
):
    db_key_account = get_scoped(session, key_account_id, current_user)

    session.delete(db_key_account)
    session.commit()

    return {'message': 'Key account deleted'}
