"""Contexto que o assistente recebe, sempre preso a uma carteira.

Este módulo é a fronteira de escopo do chat: tudo o que o modelo enxerga
sai daqui, e daqui só sai o que pertence à carteira escolhida.
"""

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from kamnews.models import (
    STATUS_ATIVO,
    Carteira,
    KeyAccount,
    Noticia,
    carteira_key_account,
)

SEM_AVALIACAO = 'não avaliada'
ROTULO_AVALIACAO = {
    'like': 'boa',
    'neutro': 'neutra',
    'dislike': 'má',
    None: SEM_AVALIACAO,
}


def key_accounts_da_carteira(
    session: Session, carteira: Carteira
) -> list[KeyAccount]:
    return list(carteira.key_accounts)


def noticias_da_carteira(
    session: Session, carteira_id: int, limite: int
) -> list[tuple[Noticia, str]]:
    """As notícias da carteira, da mais recente para a mais antiga."""
    stmt = (
        select(Noticia, KeyAccount.nome)
        .join(KeyAccount, KeyAccount.id == Noticia.key_account_id)
        .where(
            Noticia.key_account_id.in_(
                select(carteira_key_account.c.key_account_id).where(
                    carteira_key_account.c.carteira_id == carteira_id
                )
            )
        )
        .order_by(
            Noticia.data_publicacao.desc().nullslast(), Noticia.id.desc()
        )
        .limit(limite)
    )
    return list(session.execute(stmt).all())


def _bloco_key_accounts(key_accounts: list[KeyAccount]) -> str:
    if not key_accounts:
        return 'CLIENTES DA CARTEIRA: nenhum cadastrado.'

    linhas = [
        f'- {ka.nome}'
        + ('' if ka.status == STATUS_ATIVO else f' ({ka.status})')
        for ka in key_accounts
    ]
    return 'CLIENTES DA CARTEIRA:\n' + '\n'.join(linhas)


def _bloco_temperatura(linhas: list[tuple[Noticia, str]]) -> str:
    """Agregado por empresa — o mesmo recorte do dashboard."""
    if not linhas:
        return 'TEMPERATURA: sem notícias avaliadas.'

    por_empresa: dict[str, Counter] = {}
    for noticia, empresa in linhas:
        contagem = por_empresa.setdefault(empresa, Counter())
        contagem[ROTULO_AVALIACAO.get(noticia.avaliacao, SEM_AVALIACAO)] += 1

    saida = ['TEMPERATURA (contagem de notícias por avaliação):']
    for empresa in sorted(por_empresa):
        c = por_empresa[empresa]
        saida.append(
            f'- {empresa}: {c["boa"]} boas, {c["neutra"]} neutras, '
            f'{c["má"]} más, {c[SEM_AVALIACAO]} não avaliadas'
        )
    return '\n'.join(saida)


def _bloco_noticias(linhas: list[tuple[Noticia, str]]) -> str:
    """A URL fica de fora, de propósito.

    A mesma armadilha do prompt do Ollama: a URL do Google News tem 200+
    chars em base64 e não diz nada ao modelo — é um redirect. Medido numa
    carteira real, 25 notícias somavam 11.5k chars de URL contra 2k de
    texto, ou seja 69% do prompt, e estouravam o limite de tokens da
    Groq com 413. O modelo cita a notícia pelo `[id]` e pela fonte.
    """
    if not linhas:
        return 'NOTÍCIAS SALVAS: nenhuma ainda.'

    saida = ['NOTÍCIAS SALVAS (mais recentes primeiro):']
    for noticia, empresa in linhas:
        partes = [
            f'[{noticia.id}]',
            empresa,
            f'({noticia.categoria})',
        ]
        if noticia.data_publicacao:
            partes.append(noticia.data_publicacao.isoformat())
        if noticia.fonte:
            partes.append(f'fonte: {noticia.fonte}')
        rotulo = ROTULO_AVALIACAO.get(noticia.avaliacao, SEM_AVALIACAO)
        partes.append(f'avaliação: {rotulo}')
        saida.append('- ' + ' | '.join(partes))
        saida.append(f'  {noticia.texto}')
    return '\n'.join(saida)


def montar_contexto(
    session: Session, carteira: Carteira, max_noticias: int
) -> str:
    """Texto único injetado no prompt do assistente."""
    linhas = noticias_da_carteira(session, carteira.id, max_noticias)
    key_accounts = key_accounts_da_carteira(session, carteira)

    return '\n\n'.join([
        f'CARTEIRA: {carteira.nome}',
        _bloco_key_accounts(key_accounts),
        _bloco_temperatura(linhas),
        _bloco_noticias(linhas),
    ])


def carregar_carteira(session: Session, carteira_id: int) -> Carteira | None:
    return session.scalar(
        select(Carteira)
        .where(Carteira.id == carteira_id)
        .options(selectinload(Carteira.key_accounts))
    )
