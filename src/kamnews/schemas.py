from datetime import date, timedelta
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from kamnews.settings import MAX_PERIODO_DIAS, hoje_br

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


# Portfolio (contrato consumido pelo digest — não alterar a shape de
# `companies`: o export Word e o estado do frontend dependem dela)
class PortfolioPublic(BaseModel):
    name: str
    companies: list[str]
    # Aditivo: os mesmos clientes com id, para o frontend mandar o
    # `key_account_id` no POST /news/ em vez de só o nome (que é
    # ambíguo para o admin, que enxerga a carteira de todo mundo).
    key_accounts: list[KeyAccountPublic] = []


class PortfolioList(BaseModel):
    portfolios: list[PortfolioPublic]


# Avaliação da notícia
AvaliacaoLiteral = Literal['like', 'dislike', 'neutro']


class AvaliacaoSchema(BaseModel):
    # None limpa a avaliação (volta a "não avaliada").
    valor: AvaliacaoLiteral | None = None


# 'sem' filtra as não avaliadas (avaliacao IS NULL), que são um estado
# distinto de 'neutro'.
AvaliacaoFiltro = Literal['like', 'dislike', 'neutro', 'sem']


class NoticiaPublic(BaseModel):
    id: int
    texto: str
    categoria: str
    fonte: str | None = None
    url: str | None = None
    avaliacao: str | None = None

    model_config = ConfigDict(from_attributes=True)


class NoticiaHistorico(BaseModel):
    """Mesma forma de um bullet do digest, mais empresa e data.

    `data` é string ISO (não `date`) para o frontend reaproveitar o
    mesmo render dos itens do Digest.
    """

    id: int
    empresa: str
    texto: str
    categoria: str
    fonte: str | None = None
    url: str | None = None
    data: str | None = None
    avaliacao: str | None = None


class NoticiaHistoricoList(BaseModel):
    noticias: list[NoticiaHistorico]


# Assistente (chat)
class ConversaSchema(BaseModel):
    carteira_id: int


class MensagemPublic(BaseModel):
    id: int
    papel: str
    conteudo: str
    fontes: list[dict] = []

    model_config = ConfigDict(from_attributes=True)


class ConversaPublic(BaseModel):
    id: int
    titulo: str
    carteira_id: int

    model_config = ConfigDict(from_attributes=True)


class ConversaList(BaseModel):
    conversas: list[ConversaPublic]


class ConversaDetalhe(BaseModel):
    id: int
    titulo: str
    carteira_id: int
    mensagens: list[MensagemPublic] = []


class PerguntaSchema(BaseModel):
    pergunta: str


class NoticiaFiltro(BaseModel):
    """Filtros do histórico, como modelo de query.

    Agrupados num modelo para o handler não virar uma lista de oito
    parâmetros — e para o dashboard reaproveitar os mesmos recortes.
    """

    carteira_id: int | None = None
    key_account_id: int | None = None
    avaliacao: AvaliacaoFiltro | None = None
    dias: int | None = Field(default=None, ge=1)
    limit: int = Field(default=500, ge=1, le=2000)
    skip: int = Field(default=0, ge=0)


# News
class NewsRequest(BaseModel):
    company: str
    date_str: str = ''
    # Opcional: quando ausente, a empresa é resolvida pelo nome dentro
    # do escopo do usuário.
    key_account_id: int | None = None
    # Período da busca. Ausentes, valem `NEWS_WINDOW_DAYS` até hoje.
    data_inicio: date | None = None
    data_fim: date | None = None

    @model_validator(mode='after')
    def _periodo_no_limite(self) -> Self:
        """Recusa período no futuro ou além de `MAX_PERIODO_DIAS`.

        O limite conta a partir de hoje, não da largura do intervalo:
        o Google News não devolve nada útil mais para trás, e o
        frontend só oferece datas dentro dele.
        """
        hoje = hoje_br()
        if self.data_fim and self.data_fim > hoje:
            raise ValueError('A data final não pode ser no futuro.')
        if self.data_inicio:
            if self.data_inicio < hoje - timedelta(days=MAX_PERIODO_DIAS):
                raise ValueError(
                    f'O período é limitado aos últimos {MAX_PERIODO_DIAS} '
                    'dias.'
                )
            if self.data_inicio > (self.data_fim or hoje):
                raise ValueError(
                    'A data inicial não pode ser depois da final.'
                )
        return self

    def periodo(self, dias_padrao: int) -> tuple[date, date]:
        """Resolve o período, completando o que não veio na requisição."""
        fim = self.data_fim or hoje_br()
        inicio = self.data_inicio or max(
            fim - timedelta(days=dias_padrao),
            hoje_br() - timedelta(days=MAX_PERIODO_DIAS),
        )
        return inicio, fim


class NewsItem(BaseModel):
    texto: str
    fonte: str | None = None
    data: str | None = None
    url: str | None = None
    # Preenchidos na persistência; é o que liga o bullet ao banco e
    # devolve a avaliação já registrada.
    id: int | None = None
    avaliacao: str | None = None


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
