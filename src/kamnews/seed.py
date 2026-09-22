"""Dados iniciais: papéis, admin, KAMs e as carteiras do portfolios.py.

Idempotente — roda a cada boot do container (via entrypoint.sh). Nunca
apaga, nunca renomeia, nunca reativa o que foi inativado à mão e nunca
reseta a senha de um usuário já existente.
"""

import re
import unicodedata

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from kamnews.models import (
    ROLE_ADMIN,
    ROLE_KAM,
    Carteira,
    KeyAccount,
    Role,
    User,
)
from kamnews.portfolios import PORTFOLIOS
from kamnews.security import get_password_hash
from kamnews.settings import get_settings


def slugify(value: str) -> str:
    """'Rogério' -> 'rogerio'. Sem isso o email do seed sai inválido."""
    normalized = unicodedata.normalize('NFKD', value)
    ascii_only = normalized.encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', '.', ascii_only.lower()).strip('.')


def _get_or_create_role(session: Session, nome: str) -> Role:
    role = session.scalar(select(Role).where(Role.nome == nome))
    if role:
        print(f'[seed] Papel "{nome}" já existe, pulando.')
        return role

    role = Role(nome=nome)
    session.add(role)
    session.flush()
    print(f'[seed] Papel "{nome}" criado.')
    return role


def _get_or_create_user(
    session: Session, username: str, email: str, password: str, role: Role
) -> User:
    user = session.scalar(select(User).where(User.email == email))
    if user:
        print(f'[seed] Usuário "{username}" já existe, pulando.')
        return user

    user = User(
        username=username,
        email=email,
        password=get_password_hash(password),
        role_id=role.id,
    )
    session.add(user)
    session.flush()
    print(f'[seed] Usuário "{username}" criado ({email}).')
    return user


def _get_or_create_carteira(
    session: Session, nome: str, owner: User
) -> Carteira:
    carteira = session.scalar(
        select(Carteira).where(
            Carteira.nome == nome, Carteira.owner_id == owner.id
        )
    )
    if carteira:
        return carteira

    carteira = Carteira(nome=nome, owner_id=owner.id)
    session.add(carteira)
    session.flush()
    print(f'[seed] Carteira "{nome}" criada.')
    return carteira


def _get_or_create_key_account(
    session: Session, nome: str, owner: User
) -> KeyAccount:
    key_account = session.scalar(
        select(KeyAccount).where(
            KeyAccount.nome == nome, KeyAccount.owner_id == owner.id
        )
    )
    if key_account:
        return key_account

    key_account = KeyAccount(nome=nome, owner_id=owner.id)
    session.add(key_account)
    session.flush()
    return key_account


def seed_session(session: Session) -> None:
    settings = get_settings()

    role_admin = _get_or_create_role(session, ROLE_ADMIN)
    role_kam = _get_or_create_role(session, ROLE_KAM)

    _get_or_create_user(
        session,
        username='master',
        email=settings.MASTER_EMAIL,
        password=settings.MASTER_PASSWORD,
        role=role_admin,
    )

    # Os nomes das carteiras são os próprios KAMs: cada um vira usuário
    # e dono da sua carteira e das key accounts dela.
    for nome, empresas in PORTFOLIOS.items():
        kam = _get_or_create_user(
            session,
            username=nome,
            email=f'{slugify(nome)}@{settings.SEED_EMAIL_DOMAIN}',
            password=settings.SEED_KAM_PASSWORD,
            role=role_kam,
        )
        carteira = _get_or_create_carteira(session, nome, kam)

        for empresa in empresas:
            key_account = _get_or_create_key_account(session, empresa, kam)
            if key_account not in carteira.key_accounts:
                carteira.key_accounts.append(key_account)

    session.commit()


def run_seed() -> None:  # pragma: no cover
    engine = create_engine(get_settings().DATABASE_URL)
    with Session(engine) as session:
        seed_session(session)


if __name__ == '__main__':  # pragma: no cover
    run_seed()
