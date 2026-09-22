from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from kamnews.database import get_session
from kamnews.models import Role
from kamnews.schemas import RoleList
from kamnews.security import T_CurrentAdmin

router = APIRouter(prefix='/roles', tags=['roles'])

T_Session = Annotated[Session, Depends(get_session)]


@router.get('/', response_model=RoleList)
def read_roles(session: T_Session, current_admin: T_CurrentAdmin):
    """Só leitura: os papéis vêm do seed e não são gerenciáveis pela UI.

    Existe para popular o <select> do formulário de usuário sem
    hardcodar ids no JavaScript.
    """
    roles = session.scalars(select(Role).order_by(Role.nome)).all()
    return {'roles': roles}
