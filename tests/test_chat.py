from datetime import datetime, timedelta
from http import HTTPStatus

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import func, select

from kamnews.app import app
from kamnews.chat_service import (
    STATUS_EXCEDEU_COTA,
    ContextoCarteira,
    montar_mensagens,
    purgar_conversas,
    titulo_da_pergunta,
)
from kamnews.models import Conversa, KeyAccount, Mensagem, Noticia
from kamnews.noticias_service import url_hash
from kamnews.routers.chat import get_chat_llm
from kamnews.settings import Settings
from tests.conftest import auth

RESPOSTA = 'A carteira teve duas notícias relevantes.'
DUAS_MENSAGENS = 2
TITULO_LIMITE = 61
URL_GOOGLE = 'https://news.google.com/rss/articles/' + 'A' * 400


class LlmFake:
    """Responde sempre igual; se `tool_calls` vier, pede a ferramenta na
    primeira chamada e responde na segunda."""

    def __init__(self, resposta=RESPOSTA, tool_calls=None):
        self.resposta = resposta
        self.tool_calls = tool_calls or []
        self.chamadas = []

    async def ainvoke(self, mensagens):
        self.chamadas.append(mensagens)
        if self.tool_calls and len(self.chamadas) == 1:
            return AIMessage(content='', tool_calls=self.tool_calls)
        return AIMessage(content=self.resposta)


@pytest.fixture
def llm_fake():
    fake = LlmFake()
    app.dependency_overrides[get_chat_llm] = lambda: fake
    return fake


@pytest.fixture
def conversa(client, kam_token, carteira_com_ka):
    response = client.post(
        '/chat/conversas/',
        json={'carteira_id': carteira_com_ka.id},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.CREATED
    return response.json()


def _perguntar(client, token, conversa_id, pergunta='E aí?'):
    return client.post(
        f'/chat/conversas/{conversa_id}/mensagens/',
        json={'pergunta': pergunta},
        headers=auth(token),
    )


# --------------------------------------------------------------------- #
# Conversas
# --------------------------------------------------------------------- #
def test_criar_conversa(client, kam_token, carteira):
    response = client.post(
        '/chat/conversas/',
        json={'carteira_id': carteira.id},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.CREATED
    assert response.json()['carteira_id'] == carteira.id


def test_criar_conversa_exige_token(client, carteira):
    response = client.post(
        '/chat/conversas/', json={'carteira_id': carteira.id}
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_criar_conversa_carteira_de_outro(client, other_kam_token, carteira):
    response = client.post(
        '/chat/conversas/',
        json={'carteira_id': carteira.id},
        headers=auth(other_kam_token),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_listar_conversas(client, kam_token, conversa):
    response = client.get('/chat/conversas/', headers=auth(kam_token))
    assert response.status_code == HTTPStatus.OK
    ids = [c['id'] for c in response.json()['conversas']]
    assert conversa['id'] in ids


def test_conversa_de_outro_nao_aparece(client, other_kam_token, conversa):
    response = client.get('/chat/conversas/', headers=auth(other_kam_token))
    assert response.json()['conversas'] == []

    detalhe = client.get(
        f'/chat/conversas/{conversa["id"]}/', headers=auth(other_kam_token)
    )
    assert detalhe.status_code == HTTPStatus.NOT_FOUND


def test_excluir_conversa_leva_mensagens(
    client, kam_token, conversa, llm_fake, session
):
    _perguntar(client, kam_token, conversa['id'])

    response = client.delete(
        f'/chat/conversas/{conversa["id"]}/', headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.OK
    assert session.scalar(select(func.count()).select_from(Mensagem)) == 0


# --------------------------------------------------------------------- #
# Conversar
# --------------------------------------------------------------------- #
def test_enviar_mensagem(client, kam_token, conversa, llm_fake):
    response = _perguntar(client, kam_token, conversa['id'])
    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body['papel'] == 'assistant'
    assert body['conteudo'] == RESPOSTA


def test_pergunta_vazia(client, kam_token, conversa, llm_fake):
    response = _perguntar(client, kam_token, conversa['id'], '   ')
    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_pergunta_com_chaves_nao_quebra_o_template(
    client, kam_token, conversa, llm_fake
):
    """Texto do usuário não pode ser interpretado como template."""
    response = _perguntar(
        client, kam_token, conversa['id'], 'o que é {json} e {vale}?'
    )
    assert response.status_code == HTTPStatus.CREATED


def test_troca_fica_no_historico(client, kam_token, conversa, llm_fake):
    _perguntar(client, kam_token, conversa['id'], 'Primeira pergunta')

    detalhe = client.get(
        f'/chat/conversas/{conversa["id"]}/', headers=auth(kam_token)
    ).json()
    assert len(detalhe['mensagens']) == DUAS_MENSAGENS
    assert detalhe['mensagens'][0]['papel'] == 'user'
    assert detalhe['mensagens'][0]['conteudo'] == 'Primeira pergunta'
    assert detalhe['mensagens'][1]['conteudo'] == RESPOSTA
    # O título vem da primeira pergunta.
    assert detalhe['titulo'] == 'Primeira pergunta'


def test_historico_vai_para_o_modelo(client, kam_token, conversa, llm_fake):
    _perguntar(client, kam_token, conversa['id'], 'Primeira')
    _perguntar(client, kam_token, conversa['id'], 'Segunda')

    ultimas = llm_fake.chamadas[-1]
    conteudos = [m.content for m in ultimas]
    assert 'Primeira' in conteudos
    assert RESPOSTA in conteudos
    assert 'Segunda' in conteudos


def test_sem_chave_devolve_503(client, kam_token, conversa, monkeypatch):
    """Sem GROQ_API_KEY a aba fica desligada, com mensagem clara.

    Força a chave vazia: sem isso o teste leria o `.env` da máquina e,
    com uma chave preenchida, chamaria a Groq de verdade.
    """
    monkeypatch.setattr(
        'kamnews.routers.chat.get_settings',
        lambda: Settings(GROQ_API_KEY=''),
    )
    app.dependency_overrides.pop(get_chat_llm, None)

    response = _perguntar(client, kam_token, conversa['id'])
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert 'GROQ_API_KEY' in response.json()['detail']


# --------------------------------------------------------------------- #
# Contexto: só a carteira
# --------------------------------------------------------------------- #
def test_contexto_tem_dados_da_carteira(
    client, kam_token, conversa, llm_fake, key_account
):
    _perguntar(client, kam_token, conversa['id'])

    contexto = llm_fake.chamadas[0][1].content
    assert 'CARTEIRA:' in contexto
    assert key_account.nome in contexto
    assert 'TEMPERATURA' in contexto


def test_contexto_nao_vaza_outra_carteira(
    client, kam_token, conversa, llm_fake, other_kam_token
):
    """O assistente só enxerga a carteira da conversa."""
    alheio = auth(other_kam_token)
    client.post(
        '/carteiras/', json={'nome': 'Carteira Alheia'}, headers=alheio
    )
    client.post(
        '/key-accounts/', json={'nome': 'Empresa Secreta'}, headers=alheio
    )

    _perguntar(client, kam_token, conversa['id'])

    contexto = llm_fake.chamadas[0][1].content
    assert 'Empresa Secreta' not in contexto
    assert 'Carteira Alheia' not in contexto


def test_montar_mensagens_nao_templa_o_usuario():
    conversa = Conversa(user_id=1, carteira_id=1, titulo='t')
    mensagens = montar_mensagens('ctx {chave}', conversa, 'e {isto}?')
    assert mensagens[-1].content == 'e {isto}?'
    assert 'ctx {chave}' in mensagens[1].content


def test_titulo_da_pergunta_trunca():
    curto = titulo_da_pergunta('  Como vai a   carteira? ')
    assert curto == 'Como vai a carteira?'

    longo = titulo_da_pergunta('x' * 200)
    assert longo.endswith('…')
    assert len(longo) <= TITULO_LIMITE


# --------------------------------------------------------------------- #
# Expurgo
# --------------------------------------------------------------------- #
def test_purga_conversa_antiga(client, kam_token, conversa, session):
    alvo = session.scalar(
        select(Conversa).where(Conversa.id == conversa['id'])
    )
    alvo.atualizada_em = datetime.now() - timedelta(days=8)
    session.commit()

    assert purgar_conversas(session, 7) == 1
    assert session.scalar(select(func.count()).select_from(Conversa)) == 0


def test_purga_preserva_conversa_recente(client, kam_token, conversa, session):
    assert purgar_conversas(session, 7) == 0
    assert session.scalar(select(func.count()).select_from(Conversa)) == 1


def test_listar_conversas_purga(client, kam_token, conversa, session):
    alvo = session.scalar(
        select(Conversa).where(Conversa.id == conversa['id'])
    )
    alvo.atualizada_em = datetime.now() - timedelta(days=30)
    session.commit()

    response = client.get('/chat/conversas/', headers=auth(kam_token))
    assert response.json()['conversas'] == []


def test_conversar_renova_o_prazo(
    client, kam_token, conversa, llm_fake, session
):
    """Conversa velha mas em uso não pode ser apagada."""
    alvo = session.scalar(
        select(Conversa).where(Conversa.id == conversa['id'])
    )
    alvo.atualizada_em = datetime.now() - timedelta(days=6)
    session.commit()

    _perguntar(client, kam_token, conversa['id'])

    assert purgar_conversas(session, 7) == 0


def test_contexto_carteira_carrega_empresas(carteira_com_ka, key_account):
    contexto = ContextoCarteira(texto='x', empresas=[key_account.nome])
    assert key_account.nome in contexto.empresas


def test_contexto_nao_leva_url_ao_modelo(
    client, kam_token, conversa, llm_fake, session
):
    """A URL do Google News é base64 gigante e estourava a cota.

    Numa carteira real eram 11.5k chars de URL contra 2k de texto — 69%
    do prompt — e a Groq recusava com 413.
    """
    ka = session.scalar(select(KeyAccount))
    texto = 'Empresa abre fábrica no Nordeste.'
    session.add(
        Noticia(
            key_account_id=ka.id,
            categoria='expansao',
            texto=texto,
            fonte='Valor',
            url=URL_GOOGLE,
            url_hash=url_hash('expansao', texto, URL_GOOGLE),
        )
    )
    session.commit()

    _perguntar(client, kam_token, conversa['id'])

    contexto = llm_fake.chamadas[0][1].content
    assert texto in contexto
    assert 'Valor' in contexto
    assert URL_GOOGLE not in contexto


class LlmSemCota:
    """Imita o SDK do provedor: exceção crua com `status_code`."""

    def __init__(self, status):
        self.status = status

    async def ainvoke(self, mensagens):
        erro = RuntimeError('Request too large')
        erro.status_code = self.status
        raise erro


@pytest.mark.parametrize('status', sorted(STATUS_EXCEDEU_COTA))
def test_erro_de_cota_nao_vira_500(client, kam_token, conversa, status):
    """413/429 da Groq viram 502 com instrução, não 500 opaco."""
    app.dependency_overrides[get_chat_llm] = lambda: LlmSemCota(status)

    response = _perguntar(client, kam_token, conversa['id'])

    assert response.status_code == HTTPStatus.BAD_GATEWAY
    assert 'nova conversa' in response.json()['detail']
