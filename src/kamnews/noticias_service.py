"""Persistência das notícias e da avaliação (like/dislike/neutro).

O `POST /news/` sempre refaz a busca (RSS + Ollama); o banco serve para
não duplicar linha e para preservar a avaliação entre as buscas.
"""

from datetime import date, datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from kamnews.models import KeyAccount, Noticia, User
from kamnews.security import is_admin


def url_hash(categoria: str, texto: str, url: str | None) -> str:
    """Identidade da notícia dentro da key account.

    A URL é a chave natural, mas o schema a permite nula (e o modelo
    ocasionalmente devolve item sem origem). Nesses casos cai para
    categoria+texto, que é estável entre buscas enquanto o modelo não
    reescrever o bullet.
    """
    base = url.strip() if url and url.strip() else f'{categoria}|{texto}'
    return sha256(base.encode('utf-8')).hexdigest()


def _parse_data(valor: str | None) -> date | None:
    """O RSS já chega como ISO (`_format_date`); tolera lixo mesmo assim."""
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        return None


def scope_noticias(stmt, user: User):
    """Admin vê tudo; KAM vê só as notícias das key accounts dele."""
    if is_admin(user):
        return stmt
    return stmt.where(
        Noticia.key_account_id.in_(
            select(KeyAccount.id).where(KeyAccount.owner_id == user.id)
        )
    )


def persist_company_news(
    session: Session, data: dict, key_account_id: int
) -> dict:
    """Salva (ou reaproveita) cada item e devolve `data` com id/avaliação.

    Muta os dicionários de `data['temas'][*]['itens'][*]` no lugar — é o
    mesmo dict que vira `CompanyNews` na resposta.
    """
    agora = datetime.now()

    for tema in data.get('temas') or []:
        categoria = tema.get('categoria') or ''
        for item in tema.get('itens') or []:
            texto = item.get('texto') or ''
            if not texto:
                continue

            chave = url_hash(categoria, texto, item.get('url'))
            noticia = session.scalar(
                select(Noticia).where(
                    Noticia.key_account_id == key_account_id,
                    Noticia.url_hash == chave,
                )
            )

            if noticia is None:
                noticia = Noticia(
                    key_account_id=key_account_id,
                    url_hash=chave,
                    texto=texto,
                    categoria=categoria,
                    fonte=item.get('fonte'),
                    url=item.get('url'),
                    data_publicacao=_parse_data(item.get('data')),
                )
                session.add(noticia)
            else:
                # O modelo pode reescrever o bullet ou reclassificar o
                # tema entre buscas; a avaliação não é tocada.
                noticia.texto = texto
                noticia.categoria = categoria
                noticia.fonte = item.get('fonte')
                noticia.data_publicacao = _parse_data(item.get('data'))
                noticia.vista_em = agora

            session.flush()
            item['id'] = noticia.id
            item['avaliacao'] = noticia.avaliacao

    session.commit()
    return data


def set_avaliacao(
    session: Session, noticia: Noticia, valor: str | None, user: User
) -> Noticia:
    """Grava a avaliação. `valor=None` volta para "não avaliada"."""
    noticia.avaliacao = valor
    noticia.avaliado_por_id = user.id if valor else None
    noticia.avaliado_em = datetime.now() if valor else None

    session.commit()
    session.refresh(noticia)
    return noticia
