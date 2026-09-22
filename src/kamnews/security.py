from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jwt import decode, encode
from jwt.exceptions import PyJWTError
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from kamnews.database import get_session
from kamnews.models import ROLE_ADMIN, STATUS_ATIVO, User
from kamnews.settings import get_settings

pwd_context = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='auth/token')

CREDENTIALS_ERROR = 'Could not validate credentials'
PERMISSION_ERROR = 'Not enough permission'


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    settings = get_settings()
    to_encode = data.copy()

    expire = datetime.now(tz=ZoneInfo('UTC')) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode.update({'exp': expire})

    return encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def get_current_user(
    session: Session = Depends(get_session),
    token: str = Depends(oauth2_scheme),
) -> User:
    settings = get_settings()
    credential_exception = HTTPException(
        status_code=HTTPStatus.UNAUTHORIZED,
        detail=CREDENTIALS_ERROR,
        headers={'WWW-Authenticate': 'Bearer'},
    )

    try:
        payload = decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        email = payload.get('sub')
    except PyJWTError:
        raise credential_exception

    if not email:
        raise credential_exception

    user = session.scalar(select(User).where(User.email == email))

    # Inativar um usuário tem de derrubar o acesso dele, não só
    # escondê-lo da lista.
    if not user or user.status != STATUS_ATIVO:
        raise credential_exception

    return user


T_CurrentUser = Annotated[User, Depends(get_current_user)]


def is_admin(user: User) -> bool:
    return user.role.nome == ROLE_ADMIN


def get_current_admin(current_user: T_CurrentUser) -> User:
    if not is_admin(current_user):
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=PERMISSION_ERROR
        )
    return current_user


T_CurrentAdmin = Annotated[User, Depends(get_current_admin)]


def ensure_owner(obj, user: User) -> None:
    """Rede de segurança para caminhos que buscam sem filtro de dono.

    As rotas /{id}/ já filtram por dono na query e devolvem 404 — assim
    não vazam a existência de ids alheios.
    """
    if not is_admin(user) and obj.owner_id != user.id:
        raise HTTPException(
            status_code=HTTPStatus.FORBIDDEN, detail=PERMISSION_ERROR
        )
