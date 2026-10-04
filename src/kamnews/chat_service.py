"""Assistente da carteira: LangChain + Groq, com ferramentas de internet.

Segue o padrão do `chatbot-ai-study` (ChatPromptTemplate + `template |
chat`), com duas diferenças que o produto exige: o contexto vem do banco
e é preso a uma carteira, e as ferramentas decidem o que pode ser
buscado.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from kamnews.chat_tools import (
    BuscarNoticias,
    LerPagina,
    ToolError,
    buscar_noticias,
    ler_pagina,
)
from kamnews.models import PAPEL_ASSISTANT, Conversa, Mensagem
from kamnews.settings import Settings

# Uma rodada de ferramentas: o modelo pede, executamos, ele responde.
# Sem teto a conversa poderia ficar em laço e a latência estourar.
MAX_RODADAS_TOOL = 1
TITULO_MAX = 60

# Como o provedor sinaliza "seu prompt não cabe na cota".
STATUS_EXCEDEU_COTA = frozenset({413, 429})
EXCEDEU_COTA = (
    'A conversa ficou grande demais para a cota do modelo. Comece uma '
    'nova conversa ou reduza CHAT_MAX_NOTICIAS.'
)

SISTEMA = (
    'Você é um assistente de Key Account Managers no Brasil. Responde '
    'sempre em português do Brasil, de forma objetiva e executiva.\n'
    'Use PRIMEIRO os dados da carteira que estão no contexto. Se a '
    'pergunta pedir algo que não está lá, use as ferramentas para '
    'buscar notícias recentes ou ler uma página.\n'
    'Nunca invente fatos, números ou datas: se não souber, diga que não '
    'há informação disponível. Ao citar uma notícia, mencione a fonte.\n'
    'Você só tem acesso aos dados desta carteira. Se perguntarem sobre '
    'outra carteira ou outro cliente, diga que não tem acesso.'
)


class ChatError(Exception):
    """Erro tratável do assistente."""


@dataclass
class ContextoCarteira:
    """O que o assistente enxerga — e só isso.

    `empresas` é a lista de clientes que a ferramenta de busca aceita:
    andam juntas com o texto porque definem o mesmo escopo.
    """

    texto: str
    empresas: list[str]


def _historico(conversa: Conversa) -> list[BaseMessage]:
    """Mensagens como objetos, não como template.

    Passar texto do usuário como template faria o LangChain interpretar
    `{}` e quebrar em qualquer pergunta com chaves.
    """
    mensagens: list[BaseMessage] = []
    for m in conversa.mensagens:
        if m.papel == PAPEL_ASSISTANT:
            mensagens.append(AIMessage(content=m.conteudo))
        else:
            mensagens.append(HumanMessage(content=m.conteudo))
    return mensagens


def montar_mensagens(
    contexto: str, conversa: Conversa, pergunta: str
) -> list[BaseMessage]:
    template = ChatPromptTemplate.from_messages([
        ('system', SISTEMA),
        ('system', 'Contexto da carteira:\n{contexto}'),
    ])
    mensagens = list(template.format_messages(contexto=contexto))
    mensagens += _historico(conversa)
    mensagens.append(HumanMessage(content=pergunta))
    return mensagens


async def executar_tool(
    nome: str, args: dict, permitidas: list[str], settings: Settings
) -> tuple[str, dict]:
    if nome == BuscarNoticias.__name__:
        empresa = args.get('empresa', '')
        return (
            await buscar_noticias(empresa, permitidas, settings),
            {'tipo': 'noticias', 'alvo': empresa},
        )
    if nome == LerPagina.__name__:
        url = args.get('url', '')
        return (
            await ler_pagina(url, settings),
            {'tipo': 'pagina', 'alvo': url},
        )
    raise ToolError(f'Ferramenta desconhecida: {nome}')


def _status_do_erro(err: Exception) -> int | None:
    """O código HTTP que o SDK do provedor carrega, quando carrega."""
    status = getattr(err, 'status_code', None)
    if status is None:
        resposta = getattr(err, 'response', None)
        status = getattr(resposta, 'status_code', None)
    return status if isinstance(status, int) else None


async def _invocar(llm, mensagens: list[BaseMessage]):
    """Chama o modelo traduzindo falha do provedor em `ChatError`.

    Sem isto qualquer erro da Groq sobe como 500 e o usuário vê apenas
    "Internal Server Error", sem saber que o problema é a cota.
    """
    try:
        return await llm.ainvoke(mensagens)
    except ChatError:
        raise
    except Exception as err:
        if _status_do_erro(err) in STATUS_EXCEDEU_COTA:
            raise ChatError(EXCEDEU_COTA) from err
        raise ChatError(f'Falha ao consultar o modelo: {err}') from err


async def responder(
    llm,
    contexto: ContextoCarteira,
    conversa: Conversa,
    pergunta: str,
    settings: Settings,
) -> tuple[str, list[dict]]:
    """Devolve a resposta e as fontes consultadas."""
    mensagens = montar_mensagens(contexto.texto, conversa, pergunta)
    fontes: list[dict] = []

    resposta = await _invocar(llm, mensagens)

    for _ in range(MAX_RODADAS_TOOL):
        chamadas = getattr(resposta, 'tool_calls', None) or []
        if not chamadas:
            break

        mensagens.append(resposta)
        for chamada in chamadas:
            try:
                saida, fonte = await executar_tool(
                    chamada['name'],
                    chamada.get('args') or {},
                    contexto.empresas,
                    settings,
                )
                fontes.append(fonte)
            except ToolError as err:
                saida = str(err)
            mensagens.append(
                ToolMessage(content=saida, tool_call_id=chamada['id'])
            )

        resposta = await _invocar(llm, mensagens)

    texto = (resposta.content or '').strip()
    if not texto:
        raise ChatError('O assistente não retornou uma resposta.')
    return texto, fontes


def titulo_da_pergunta(pergunta: str) -> str:
    limpa = ' '.join(pergunta.split())
    if len(limpa) <= TITULO_MAX:
        return limpa or 'Nova conversa'
    return limpa[:TITULO_MAX].rstrip() + '…'


def registrar_troca(
    session: Session,
    conversa: Conversa,
    pergunta: str,
    resposta: str,
    fontes: list[dict],
) -> Mensagem:
    session.add(
        Mensagem(conversa_id=conversa.id, papel='user', conteudo=pergunta)
    )
    mensagem = Mensagem(
        conversa_id=conversa.id,
        papel=PAPEL_ASSISTANT,
        conteudo=resposta,
        fontes=json.dumps(fontes, ensure_ascii=False) if fontes else None,
    )
    session.add(mensagem)

    # Move a conversa para o fim da fila do expurgo.
    conversa.atualizada_em = datetime.now()

    session.commit()
    session.refresh(mensagem)
    return mensagem


def purgar_conversas(session: Session, dias: int) -> int:
    """Apaga conversas paradas há mais de `dias`. As mensagens vão junto
    pelo ondelete CASCADE."""
    limite = datetime.now() - timedelta(days=dias)
    ids = list(
        session.scalars(
            select(Conversa.id).where(Conversa.atualizada_em < limite)
        )
    )
    if not ids:
        return 0

    session.execute(delete(Mensagem).where(Mensagem.conversa_id.in_(ids)))
    session.execute(delete(Conversa).where(Conversa.id.in_(ids)))
    session.commit()
    return len(ids)
