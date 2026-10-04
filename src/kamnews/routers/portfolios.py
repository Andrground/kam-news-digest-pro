from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from kamnews.database import get_session
from kamnews.models import STATUS_ATIVO, Carteira
from kamnews.routers.carteiras import scope
from kamnews.schemas import PortfolioList, PortfolioPublic
from kamnews.security import T_CurrentUser

router = APIRouter(prefix='/portfolios', tags=['portfolios'])

T_Session = Annotated[Session, Depends(get_session)]


def _to_public(carteira: Carteira) -> PortfolioPublic:
    """`companies` mantém a shape do dicionário hardcoded — o digest e o
    export Word dependem dela. `key_accounts` é aditivo e carrega o id,
    que o frontend manda no POST /news/."""
    ativas = [
        key_account
        for key_account in carteira.key_accounts
        if key_account.status == STATUS_ATIVO
    ]
    return PortfolioPublic(
        name=carteira.nome,
        companies=[key_account.nome for key_account in ativas],
        key_accounts=ativas,
    )


@router.get('/', response_model=PortfolioList)
def read_portfolios(session: T_Session, current_user: T_CurrentUser):
    carteiras = session.scalars(
        scope(
            select(Carteira).where(Carteira.status == STATUS_ATIVO),
            current_user,
        )
        .options(selectinload(Carteira.key_accounts))
        .order_by(Carteira.nome)
    ).all()

    return {'portfolios': [_to_public(carteira) for carteira in carteiras]}


@router.get('/{name}/', response_model=PortfolioPublic)
def read_portfolio(name: str, session: T_Session, current_user: T_CurrentUser):
    carteira = session.scalar(
        scope(
            select(Carteira).where(
                Carteira.nome == name, Carteira.status == STATUS_ATIVO
            ),
            current_user,
        ).options(selectinload(Carteira.key_accounts))
    )
    if not carteira:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail='Portfolio not found'
        )

    return _to_public(carteira)
