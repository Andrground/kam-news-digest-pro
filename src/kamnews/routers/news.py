from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from kamnews.database import get_session
from kamnews.models import KeyAccount
from kamnews.news_service import (
    NewsServiceError,
    Periodo,
    fetch_company_news,
)
from kamnews.noticias_service import persist_company_news
from kamnews.routers.key_accounts import scope
from kamnews.schemas import CompanyNews, NewsRequest
from kamnews.security import T_CurrentUser
from kamnews.settings import get_settings

router = APIRouter(prefix='/news', tags=['news'])

T_Session = Annotated[Session, Depends(get_session)]

NewsFetcher = Callable[[str, str, Periodo], Awaitable[dict]]

KEY_ACCOUNT_NOT_FOUND = (
    'Empresa não cadastrada como key account. '
    'Cadastre-a na aba Cadastro para guardar o histórico.'
)


def get_news_fetcher() -> NewsFetcher:
    return fetch_company_news


T_Fetcher = Annotated[NewsFetcher, Depends(get_news_fetcher)]


def _resolve_key_account(
    session: Session, request: NewsRequest, company: str, user
) -> KeyAccount:
    """Resolve a key account pelo id ou, na falta dele, pelo nome.

    O nome sozinho é ambíguo para o admin, que enxerga a carteira de
    todos: se duas pessoas têm 'Vale', a busca por nome acha as duas.
    Nesse caso, prioriza a do próprio usuário e cai para o menor id —
    determinístico. O frontend manda o id justamente para não depender
    desse desempate.
    """
    if request.key_account_id is not None:
        stmt = select(KeyAccount).where(
            KeyAccount.id == request.key_account_id
        )
        key_account = session.scalar(scope(stmt, user))
        if not key_account:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail=KEY_ACCOUNT_NOT_FOUND,
            )
        return key_account

    stmt = select(KeyAccount).where(KeyAccount.nome == company)
    encontradas = session.scalars(
        scope(stmt, user).order_by(KeyAccount.id)
    ).all()
    if not encontradas:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail=KEY_ACCOUNT_NOT_FOUND
        )

    proprias = [k for k in encontradas if k.owner_id == user.id]
    return proprias[0] if proprias else encontradas[0]


@router.post('/', response_model=CompanyNews)
async def search_news(
    request: NewsRequest,
    fetch: T_Fetcher,
    session: T_Session,
    current_user: T_CurrentUser,
):
    company = request.company.strip()
    if not company:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail='Empresa não informada.'
        )

    key_account = _resolve_key_account(session, request, company, current_user)

    try:
        periodo = request.periodo(get_settings().NEWS_WINDOW_DAYS)
        data = await fetch(company, request.date_str, periodo)
    except NewsServiceError as err:
        raise HTTPException(
            status_code=HTTPStatus.BAD_GATEWAY, detail=str(err)
        ) from err

    return persist_company_news(session, data, key_account.id)
