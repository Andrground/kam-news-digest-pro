from sqlalchemy import Column, ForeignKey, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, registry, relationship

table_registry = registry()

STATUS_ATIVO = 'ativo'
STATUS_INATIVO = 'inativo'

ROLE_ADMIN = 'Administrador'
ROLE_KAM = 'KAM'

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
