from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

StatusLiteral = Literal['ativo', 'inativo']


class Message(BaseModel):
    message: str


# Auth
class Token(BaseModel):
    access_token: str
    token_type: str


# Role
class RolePublic(BaseModel):
    id: int
    nome: str

    model_config = ConfigDict(from_attributes=True)


class RoleList(BaseModel):
    roles: list[RolePublic]


# User
class UserSchema(BaseModel):
    username: str
    email: EmailStr
    password: str
    role_id: int
    status: StatusLiteral = 'ativo'


class UserUpdate(BaseModel):
    username: str
    email: EmailStr
    # None = não alterar a senha. Sem isso, editar o nome de um usuário
    # obrigaria o admin a inventar uma senha nova.
    password: str | None = None
    role_id: int
    status: StatusLiteral = 'ativo'


class UserPublic(BaseModel):
    # Nunca inclua `password` aqui.
    id: int
    username: str
    email: EmailStr
    status: str
    role_id: int
    role: RolePublic | None = None

    model_config = ConfigDict(from_attributes=True)


class UserList(BaseModel):
    users: list[UserPublic]


# Key account
class KeyAccountSchema(BaseModel):
    nome: str
    status: StatusLiteral = 'ativo'


class KeyAccountPublic(BaseModel):
    # Sem `carteiras`: evita recursão na serialização.
    id: int
    nome: str
    status: str
    owner_id: int

    model_config = ConfigDict(from_attributes=True)


class KeyAccountList(BaseModel):
    key_accounts: list[KeyAccountPublic]


# Carteira
class CarteiraSchema(BaseModel):
    # Sem `owner_id`: o dono vem sempre do token, nunca do corpo.
    nome: str
    status: StatusLiteral = 'ativo'


class CarteiraPublic(BaseModel):
    id: int
    nome: str
    status: str
    owner_id: int
    # Todos os vínculos, independentemente de status — a aba Cadastro
    # precisa mostrar um cliente inativo que está vinculado. Só o
    # /portfolios/ filtra.
    key_accounts: list[KeyAccountPublic] = []

    model_config = ConfigDict(from_attributes=True)


class CarteiraList(BaseModel):
    carteiras: list[CarteiraPublic]


# Portfolio (contrato consumido pelo digest — não alterar a shape)
class PortfolioPublic(BaseModel):
    name: str
    companies: list[str]


class PortfolioList(BaseModel):
    portfolios: list[PortfolioPublic]


# News
class NewsRequest(BaseModel):
    company: str
    date_str: str = ''


class NewsItem(BaseModel):
    texto: str
    fonte: str | None = None
    data: str | None = None
    url: str | None = None


class NewsTheme(BaseModel):
    categoria: str
    itens: list[NewsItem] = []


class CompanyNews(BaseModel):
    empresa: str
    tem_noticias: bool = Field(default=True, alias='temNoticias')
    manchete_principal: str | None = Field(
        default=None, alias='manchetePrincipal'
    )
    resumo: str | None = None
    temas: list[NewsTheme] = []

    model_config = ConfigDict(populate_by_name=True)
