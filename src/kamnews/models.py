from datetime import date, datetime

from sqlalchemy import (
    Column,
    ForeignKey,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, registry, relationship

table_registry = registry()

STATUS_ATIVO = 'ativo'
STATUS_INATIVO = 'inativo'

ROLE_ADMIN = 'Administrador'
ROLE_KAM = 'KAM'

# Avaliação da notícia. A ausência (None) é um quarto estado e não é o
# mesmo que 'neutro': significa "ainda não olhei", o que o dashboard de
# temperatura precisa distinguir de "olhei e achei neutra".
AVALIACAO_LIKE = 'like'
AVALIACAO_DISLIKE = 'dislike'
AVALIACAO_NEUTRO = 'neutro'
AVALIACOES = (AVALIACAO_LIKE, AVALIACAO_DISLIKE, AVALIACAO_NEUTRO)

# sha256 em hexadecimal.
URL_HASH_LEN = 64

PAPEL_USER = 'user'
PAPEL_ASSISTANT = 'assistant'

# Vínculo N:N. O ondelete cobre o que passa por fora do ORM (psql, um
# delete() em massa, correção via migration); o ORM já limpa sozinho.
carteira_key_account = Table(
    'carteira_key_account',
    table_registry.metadata,
    Column(
        'carteira_id',
        ForeignKey('carteira.id', ondelete='CASCADE'),
        primary_key=True,
    ),
    Column(
        'key_account_id',
        ForeignKey('key_account.id', ondelete='CASCADE'),
        primary_key=True,
    ),
)


@table_registry.mapped_as_dataclass
class Role:
    __tablename__ = 'role'

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    nome: Mapped[str] = mapped_column(unique=True)


@table_registry.mapped_as_dataclass
class User:
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str] = mapped_column(unique=True)
    password: Mapped[str]
    role_id: Mapped[int] = mapped_column(ForeignKey('role.id'))
    status: Mapped[str] = mapped_column(default=STATUS_ATIVO)
    # lazy='joined': get_current_user roda em toda requisição autenticada
    # e sempre precisa do nome do papel.
    role: Mapped['Role'] = relationship(init=False, repr=False, lazy='joined')


@table_registry.mapped_as_dataclass
class Carteira:
    __tablename__ = 'carteira'
    # Unicidade por dono, não global: com nome único global, o primeiro
    # KAM a cadastrar um nome bloquearia todos os outros.
    __table_args__ = (UniqueConstraint('nome', 'owner_id'),)

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    nome: Mapped[str]
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(default=STATUS_ATIVO)
    # init=False (sem default_factory: os dois juntos dão ArgumentError).
    # repr=False evita que o __repr__ do dataclass dispare lazy load.
    key_accounts: Mapped[list['KeyAccount']] = relationship(
        init=False,
        repr=False,
        secondary=carteira_key_account,
        back_populates='carteiras',
        order_by='KeyAccount.nome',
    )


@table_registry.mapped_as_dataclass
class KeyAccount:
    __tablename__ = 'key_account'
    __table_args__ = (UniqueConstraint('nome', 'owner_id'),)

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    nome: Mapped[str]
    owner_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(default=STATUS_ATIVO)
    carteiras: Mapped[list['Carteira']] = relationship(
        init=False,
        repr=False,
        secondary=carteira_key_account,
        back_populates='key_accounts',
        order_by='Carteira.nome',
    )


@table_registry.mapped_as_dataclass
class Noticia:
    """Notícia guardada por key account, com a avaliação do usuário.

    A unicidade é `(key_account_id, url_hash)`: rebuscar a mesma empresa
    reaproveita a linha em vez de duplicar, e a avaliação sobrevive. O
    hash existe porque as URLs do Google News passam de 200 chars em
    base64 — indexar a URL crua seria caro.
    """

    __tablename__ = 'noticia'
    __table_args__ = (UniqueConstraint('key_account_id', 'url_hash'),)

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    key_account_id: Mapped[int] = mapped_column(
        ForeignKey('key_account.id', ondelete='CASCADE')
    )
    url_hash: Mapped[str] = mapped_column(String(URL_HASH_LEN))
    texto: Mapped[str]
    categoria: Mapped[str]
    fonte: Mapped[str | None] = mapped_column(default=None)
    url: Mapped[str | None] = mapped_column(default=None)
    data_publicacao: Mapped[date | None] = mapped_column(default=None)
    avaliacao: Mapped[str | None] = mapped_column(default=None)
    avaliado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey('users.id'), default=None
    )
    avaliado_em: Mapped[datetime | None] = mapped_column(default=None)
    criada_em: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    # Última vez que a notícia apareceu numa busca. Atualizada
    # explicitamente: o `onupdate` não dispara quando nada mais muda.
    vista_em: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )


@table_registry.mapped_as_dataclass
class Conversa:
    """Uma conversa do assistente, sempre presa a uma carteira.

    A carteira é o escopo do contexto: o assistente só enxerga os dados
    dela. Conversas passam por expurgo (`CHAT_HISTORY_DAYS`).
    """

    __tablename__ = 'conversa'

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    carteira_id: Mapped[int] = mapped_column(
        ForeignKey('carteira.id', ondelete='CASCADE')
    )
    titulo: Mapped[str]
    criada_em: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    # Move a cada mensagem — é o que o expurgo olha, para não apagar
    # uma conversa antiga que ainda está em uso.
    atualizada_em: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    mensagens: Mapped[list['Mensagem']] = relationship(
        init=False,
        repr=False,
        back_populates='conversa',
        cascade='all, delete-orphan',
        order_by='Mensagem.id',
    )


@table_registry.mapped_as_dataclass
class Mensagem:
    __tablename__ = 'mensagem'

    id: Mapped[int] = mapped_column(init=False, primary_key=True)
    conversa_id: Mapped[int] = mapped_column(
        ForeignKey('conversa.id', ondelete='CASCADE')
    )
    papel: Mapped[str]
    conteudo: Mapped[str]
    # Fontes consultadas (RSS/página) para montar a resposta, em JSON.
    fontes: Mapped[str | None] = mapped_column(default=None)
    criada_em: Mapped[datetime] = mapped_column(
        init=False, server_default=func.now()
    )
    conversa: Mapped['Conversa'] = relationship(
        init=False, repr=False, back_populates='mensagens'
    )
