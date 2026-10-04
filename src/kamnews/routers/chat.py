import json
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from langchain_groq import ChatGroq
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from kamnews.chat_context import carregar_carteira, montar_contexto
from kamnews.chat_service import (
    ChatError,
    ContextoCarteira,
    purgar_conversas,
    registrar_troca,
    responder,
    titulo_da_pergunta,
)
from kamnews.chat_tools import BuscarNoticias, LerPagina
from kamnews.database import get_session
from kamnews.models import Carteira, Conversa, User
from kamnews.routers.carteiras import scope as scope_carteiras
from kamnews.schemas import (
    ConversaDetalhe,
    ConversaList,
    ConversaPublic,
    ConversaSchema,
    MensagemPublic,
    Message,
    PerguntaSchema,
)
from kamnews.security import T_CurrentUser, is_admin
from kamnews.settings import get_settings

router = APIRouter(prefix='/chat', tags=['chat'])

T_Session = Annotated[Session, Depends(get_session)]

CONVERSA_NOT_FOUND = 'Conversa not found'
CARTEIRA_NOT_FOUND = 'Carteira not found'
SEM_CHAVE = 'Assistente indisponível: configure GROQ_API_KEY para habilitá-lo.'


def get_chat_llm():
    """Modelo do assistente, como dependência — os testes substituem.

    Sem chave a aba fica desligada com 503, em vez de estourar no meio
    da conversa.
    """
    settings = get_settings()
    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail=SEM_CHAVE
        )

    llm = ChatGroq(
        model=settings.CHAT_MODEL,
        api_key=settings.GROQ_API_KEY,
        timeout=settings.CHAT_TIMEOUT,
    )
    return llm.bind_tools([BuscarNoticias, LerPagina])


T_Llm = Annotated[object, Depends(get_chat_llm)]


def _scope_conversas(stmt, user: User):
    """Admin vê tudo; cada usuário vê só as próprias conversas."""
    if is_admin(user):
        return stmt
    return stmt.where(Conversa.user_id == user.id)


def _get_conversa(session: Session, conversa_id: int, user: User) -> Conversa:
    conversa = session.scalar(
        _scope_conversas(
            select(Conversa)
            .where(Conversa.id == conversa_id)
            .options(selectinload(Conversa.mensagens)),
            user,
        )
    )
    if not conversa:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail=CONVERSA_NOT_FOUND
        )
    return conversa


def _carteira_no_escopo(
    session: Session, carteira_id: int, user: User
) -> Carteira:
    """404 fora do escopo, igual aos outros routers."""
    visivel = session.scalar(
        scope_carteiras(
            select(Carteira.id).where(Carteira.id == carteira_id), user
        )
    )
    carteira = carregar_carteira(session, carteira_id) if visivel else None
    if carteira is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail=CARTEIRA_NOT_FOUND
        )
    return carteira


def _mensagens_public(conversa: Conversa) -> list[MensagemPublic]:
    return [
        MensagemPublic(
            id=m.id,
            papel=m.papel,
            conteudo=m.conteudo,
            fontes=json.loads(m.fontes) if m.fontes else [],
        )
        for m in conversa.mensagens
    ]


@router.get('/conversas/', response_model=ConversaList)
def read_conversas(session: T_Session, current_user: T_CurrentUser):
    purgar_conversas(session, get_settings().CHAT_HISTORY_DAYS)

    conversas = session.scalars(
        _scope_conversas(select(Conversa), current_user).order_by(
            Conversa.atualizada_em.desc()
        )
    ).all()
    return {'conversas': conversas}


@router.post(
    '/conversas/',
    status_code=HTTPStatus.CREATED,
    response_model=ConversaPublic,
)
def create_conversa(
    dados: ConversaSchema, session: T_Session, current_user: T_CurrentUser
):
    carteira = _carteira_no_escopo(session, dados.carteira_id, current_user)

    conversa = Conversa(
        user_id=current_user.id,
        carteira_id=carteira.id,
        titulo='Nova conversa',
    )
    session.add(conversa)
    session.commit()
    session.refresh(conversa)
    return conversa


@router.get('/conversas/{conversa_id}/', response_model=ConversaDetalhe)
def read_conversa(
    conversa_id: int, session: T_Session, current_user: T_CurrentUser
):
    conversa = _get_conversa(session, conversa_id, current_user)
    return ConversaDetalhe(
        id=conversa.id,
        titulo=conversa.titulo,
        carteira_id=conversa.carteira_id,
        mensagens=_mensagens_public(conversa),
    )


@router.delete('/conversas/{conversa_id}/', response_model=Message)
def delete_conversa(
    conversa_id: int, session: T_Session, current_user: T_CurrentUser
):
    conversa = _get_conversa(session, conversa_id, current_user)

    session.delete(conversa)
    session.commit()
    return {'message': 'Conversa deleted'}


@router.post(
    '/conversas/{conversa_id}/mensagens/',
    status_code=HTTPStatus.CREATED,
    response_model=MensagemPublic,
)
async def enviar_mensagem(
    conversa_id: int,
    dados: PerguntaSchema,
    session: T_Session,
    current_user: T_CurrentUser,
    llm: T_Llm,
):
    pergunta = dados.pergunta.strip()
    if not pergunta:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail='Pergunta vazia.'
        )

    conversa = _get_conversa(session, conversa_id, current_user)
    carteira = _carteira_no_escopo(session, conversa.carteira_id, current_user)
    settings = get_settings()

    contexto = ContextoCarteira(
        texto=montar_contexto(session, carteira, settings.CHAT_MAX_NOTICIAS),
        empresas=[ka.nome for ka in carteira.key_accounts],
    )

    try:
        texto, fontes = await responder(
            llm, contexto, conversa, pergunta, settings
        )
    except ChatError as err:
        raise HTTPException(
            status_code=HTTPStatus.BAD_GATEWAY, detail=str(err)
        ) from err

    if conversa.titulo == 'Nova conversa':
        conversa.titulo = titulo_da_pergunta(pergunta)

    mensagem = registrar_troca(session, conversa, pergunta, texto, fontes)
    return MensagemPublic(
        id=mensagem.id,
        papel=mensagem.papel,
        conteudo=mensagem.conteudo,
        fontes=fontes,
    )
