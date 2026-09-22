from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from kamnews.database import get_session
from kamnews.models import Carteira, User
from kamnews.routers.key_accounts import get_scoped as get_scoped_ka
from kamnews.schemas import (
    CarteiraList,
    CarteiraPublic,
    CarteiraSchema,
    Message,
    StatusLiteral,
)
from kamnews.security import T_CurrentUser, is_admin

router = APIRouter(prefix='/carteiras', tags=['carteiras'])

T_Session = Annotated[Session, Depends(get_session)]

NOT_FOUND = 'Carteira not found'
DUPLICATE = 'Carteira name already exists'


def scope(stmt, user: User):
    """Admin vê tudo; KAM vê só o que é dele."""
    if is_admin(user):
        return stmt
    return stmt.where(Carteira.owner_id == user.id)


def _get_scoped(session: Session, carteira_id: int, user: User) -> Carteira:
    """404 (e não 403) fora do escopo: não vaza ids alheios."""
    carteira = session.scalar(
        scope(
            select(Carteira)
            .where(Carteira.id == carteira_id)
            .options(selectinload(Carteira.key_accounts)),
            user,
        )
    )
    if not carteira:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=NOT_FOUND)
    return carteira


def _check_duplicate(
    session: Session,
    nome: str,
    owner_id: int,
    carteira_id: int | None = None,
) -> None:
    stmt = select(Carteira).where(
        Carteira.nome == nome, Carteira.owner_id == owner_id
    )
    if carteira_id is not None:
        stmt = stmt.where(Carteira.id != carteira_id)

    if session.scalar(stmt):
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail=DUPLICATE
        )


@router.get('/', response_model=CarteiraList)
def read_carteiras(
    session: T_Session,
    current_user: T_CurrentUser,
    status: StatusLiteral | None = None,
    limit: int = 100,
    skip: int = 0,
):
    stmt = scope(select(Carteira), current_user)
    if status:
        stmt = stmt.where(Carteira.status == status)

    carteiras = session.scalars(
        stmt.options(selectinload(Carteira.key_accounts))
        .order_by(Carteira.nome)
        .limit(limit)
        .offset(skip)
    ).all()
    return {'carteiras': carteiras}


@router.get('/{carteira_id}/', response_model=CarteiraPublic)
def read_carteira(
    carteira_id: int, session: T_Session, current_user: T_CurrentUser
):
    return _get_scoped(session, carteira_id, current_user)


@router.post(
    '/', status_code=HTTPStatus.CREATED, response_model=CarteiraPublic
)
def create_carteira(
    carteira: CarteiraSchema,
    session: T_Session,
    current_user: T_CurrentUser,
):
    _check_duplicate(session, carteira.nome, current_user.id)

    # owner_id vem sempre do token, nunca do corpo.
    db_carteira = Carteira(
        nome=carteira.nome,
        owner_id=current_user.id,
        status=carteira.status,
    )
    session.add(db_carteira)
    session.commit()
    session.refresh(db_carteira)

    return db_carteira


@router.put('/{carteira_id}/', response_model=CarteiraPublic)
def update_carteira(
    carteira_id: int,
    carteira: CarteiraSchema,
    session: T_Session,
    current_user: T_CurrentUser,
):
    db_carteira = _get_scoped(session, carteira_id, current_user)
    _check_duplicate(session, carteira.nome, db_carteira.owner_id, carteira_id)

    db_carteira.nome = carteira.nome
    db_carteira.status = carteira.status

    session.commit()
    session.refresh(db_carteira)

    return db_carteira


@router.delete('/{carteira_id}/', response_model=Message)
def delete_carteira(
    carteira_id: int, session: T_Session, current_user: T_CurrentUser
):
    db_carteira = _get_scoped(session, carteira_id, current_user)

    session.delete(db_carteira)
    session.commit()

    return {'message': 'Carteira deleted'}


@router.post(
    '/{carteira_id}/key-accounts/{key_account_id}/',
    response_model=CarteiraPublic,
)
def link_key_account(
    carteira_id: int,
    key_account_id: int,
    session: T_Session,
    current_user: T_CurrentUser,
):
    """Idempotente: o chip alterna, e um duplo clique não pode virar erro."""
    carteira = _get_scoped(session, carteira_id, current_user)
    key_account = get_scoped_ka(session, key_account_id, current_user)

    if key_account not in carteira.key_accounts:
        carteira.key_accounts.append(key_account)
        session.commit()
        session.refresh(carteira)

    return carteira


@router.delete(
    '/{carteira_id}/key-accounts/{key_account_id}/',
    response_model=CarteiraPublic,
)
def unlink_key_account(
    carteira_id: int,
    key_account_id: int,
    session: T_Session,
    current_user: T_CurrentUser,
):
    carteira = _get_scoped(session, carteira_id, current_user)
    key_account = get_scoped_ka(session, key_account_id, current_user)

    if key_account in carteira.key_accounts:
        carteira.key_accounts.remove(key_account)
        session.commit()
        session.refresh(carteira)

    return carteira
