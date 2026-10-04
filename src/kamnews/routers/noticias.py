from datetime import date, timedelta
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from kamnews.database import get_session
from kamnews.models import KeyAccount, Noticia, carteira_key_account
from kamnews.noticias_service import scope_noticias, set_avaliacao
from kamnews.schemas import (
    AvaliacaoSchema,
    NoticiaFiltro,
    NoticiaHistorico,
    NoticiaHistoricoList,
    NoticiaPublic,
)
from kamnews.security import T_CurrentUser

router = APIRouter(prefix='/noticias', tags=['noticias'])

T_Session = Annotated[Session, Depends(get_session)]

NOT_FOUND = 'Notícia not found'
SEM_AVALIACAO = 'sem'


@router.get('/', response_model=NoticiaHistoricoList)
def read_noticias(
    session: T_Session,
    current_user: T_CurrentUser,
    filtro: Annotated[NoticiaFiltro, Query()],
):
    """Histórico do que já foi buscado, para não refazer a busca."""
    stmt = scope_noticias(
        select(Noticia, KeyAccount.nome).join(
            KeyAccount, KeyAccount.id == Noticia.key_account_id
        ),
        current_user,
    )

    if filtro.key_account_id is not None:
        stmt = stmt.where(Noticia.key_account_id == filtro.key_account_id)

    if filtro.carteira_id is not None:
        stmt = stmt.where(
            Noticia.key_account_id.in_(
                select(carteira_key_account.c.key_account_id).where(
                    carteira_key_account.c.carteira_id == filtro.carteira_id
                )
            )
        )

    if filtro.avaliacao == SEM_AVALIACAO:
        stmt = stmt.where(Noticia.avaliacao.is_(None))
    elif filtro.avaliacao:
        stmt = stmt.where(Noticia.avaliacao == filtro.avaliacao)

    if filtro.dias is not None:
        # Notícia sem data fica de fora de qualquer recorte de período —
        # não dá para afirmar que cai dentro dele.
        stmt = stmt.where(
            Noticia.data_publicacao
            >= date.today() - timedelta(days=filtro.dias)
        )

    linhas = session.execute(
        stmt
        .order_by(
            KeyAccount.nome,
            Noticia.data_publicacao.desc().nullslast(),
            Noticia.id,
        )
        .limit(filtro.limit)
        .offset(filtro.skip)
    ).all()

    return {
        'noticias': [
            NoticiaHistorico(
                id=noticia.id,
                empresa=empresa,
                texto=noticia.texto,
                categoria=noticia.categoria,
                fonte=noticia.fonte,
                url=noticia.url,
                data=(
                    noticia.data_publicacao.isoformat()
                    if noticia.data_publicacao
                    else None
                ),
                avaliacao=noticia.avaliacao,
            )
            for noticia, empresa in linhas
        ]
    }


@router.put('/{noticia_id}/avaliacao/', response_model=NoticiaPublic)
def avaliar_noticia(
    noticia_id: int,
    avaliacao: AvaliacaoSchema,
    session: T_Session,
    current_user: T_CurrentUser,
):
    """`valor` nulo limpa a avaliação — é o "desfazer" dos botões."""
    noticia = session.scalar(
        scope_noticias(
            select(Noticia).where(Noticia.id == noticia_id), current_user
        )
    )
    if not noticia:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail=NOT_FOUND)

    return set_avaliacao(session, noticia, avaliacao.valor, current_user)
