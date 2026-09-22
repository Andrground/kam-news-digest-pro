from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from kamnews.news_service import NewsServiceError, fetch_company_news
from kamnews.schemas import CompanyNews, NewsRequest
from kamnews.security import T_CurrentUser

router = APIRouter(prefix='/news', tags=['news'])

NewsFetcher = Callable[[str, str], Awaitable[dict]]


def get_news_fetcher() -> NewsFetcher:
    return fetch_company_news


T_Fetcher = Annotated[NewsFetcher, Depends(get_news_fetcher)]


@router.post('/', response_model=CompanyNews)
async def search_news(
    request: NewsRequest, fetch: T_Fetcher, current_user: T_CurrentUser
):
    company = request.company.strip()
    if not company:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail='Empresa não informada.'
        )
    try:
        return await fetch(company, request.date_str)
    except NewsServiceError as err:
        raise HTTPException(
            status_code=HTTPStatus.BAD_GATEWAY, detail=str(err)
        ) from err
