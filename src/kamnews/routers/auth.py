from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from kamnews.database import get_session
from kamnews.models import STATUS_ATIVO, User
from kamnews.schemas import Token
from kamnews.security import (
    T_CurrentUser,
    create_access_token,
    verify_password,
)

router = APIRouter(prefix='/auth', tags=['auth'])

T_Session = Annotated[Session, Depends(get_session)]
T_OAuth2Form = Annotated[OAuth2PasswordRequestForm, Depends()]

LOGIN_ERROR = 'Incorrect username or password'


@router.post('/token', response_model=Token)
def login_for_access_token(session: T_Session, form_data: T_OAuth2Form):
    user = session.scalar(select(User).where(User.email == form_data.username))

    # Usuário inativo recebe a mesma mensagem: não revela que a conta
    # existe.
    if (
        not user
        or user.status != STATUS_ATIVO
        or not verify_password(form_data.password, user.password)
    ):
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail=LOGIN_ERROR
        )

    return {
        'access_token': create_access_token(data={'sub': user.email}),
        'token_type': 'Bearer',
    }


@router.post('/refresh_token', response_model=Token)
def refresh_access_token(current_user: T_CurrentUser):
    return {
        'access_token': create_access_token(data={'sub': current_user.email}),
        'token_type': 'Bearer',
    }
