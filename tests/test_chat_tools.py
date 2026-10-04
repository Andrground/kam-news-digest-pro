from http import HTTPStatus

import httpx
import pytest

from kamnews.chat_service import executar_tool
from kamnews.chat_tools import (
    MAX_REDIRECTS,
    BuscarNoticias,
    LerPagina,
    ToolError,
    buscar_noticias,
    extrair_texto,
    ler_pagina,
    validar_url,
)
from kamnews.settings import Settings

# Endereços que o assistente não pode alcançar: são a rede interna do
# compose (banco, Ollama) e o metadata da nuvem.
TRUNCADO_LEN = 101

URLS_BLOQUEADAS = [
    'http://localhost:8000/',
    'http://127.0.0.1/',
    'http://169.254.169.254/latest/meta-data/',
    'http://10.0.0.5/',
    'http://192.168.0.1/',
    'http://172.17.0.1/',
    'http://kamnews_database:5432/',
    'http://[::1]/',
]

URLS_INVALIDAS = [
    'file:///etc/passwd',
    'ftp://exemplo.com/x',
    'gopher://exemplo.com',
    'nao-e-url',
    '',
]


@pytest.mark.parametrize('url', URLS_BLOQUEADAS)
def test_ler_pagina_bloqueia_rede_interna(url):
    with pytest.raises(ToolError):
        validar_url(url)


@pytest.mark.parametrize('url', URLS_INVALIDAS)
def test_ler_pagina_rejeita_esquema_invalido(url):
    with pytest.raises(ToolError):
        validar_url(url)


def test_valida_url_publica():
    assert validar_url('https://exemplo.com/materia') == (
        'https://exemplo.com/materia'
    )


def test_extrair_texto_remove_script_e_estilo():
    html = """
    <html><head><style>p{color:red}</style></head>
    <body><script>alert(1)</script>
    <nav>menu</nav><p>Notícia   importante</p></body></html>
    """
    texto = extrair_texto(html, 1000)
    assert 'Notícia importante' in texto
    assert 'alert' not in texto
    assert 'color:red' not in texto
    assert 'menu' not in texto


def test_extrair_texto_trunca():
    texto = extrair_texto('<p>' + ('a' * 500) + '</p>', 100)
    assert len(texto) == TRUNCADO_LEN
    assert texto.endswith('…')


async def test_buscar_noticias_recusa_empresa_fora_da_carteira():
    """A fronteira de escopo: só clientes da carteira."""
    with pytest.raises(ToolError) as erro:
        await buscar_noticias('Petrobras', ['Vale', 'Gerdau'], Settings())

    assert 'não é um cliente desta carteira' in str(erro.value)
    assert 'Vale' in str(erro.value)


async def test_buscar_noticias_ignora_caixa_e_espaco(monkeypatch):
    async def _fake_rss(company, settings):
        assert company == 'Vale'
        return [
            {
                'titulo': 'Vale anuncia resultado',
                'fonte': 'Valor',
                'data': '2026-09-01',
                'url': 'https://exemplo.com/1',
            }
        ]

    monkeypatch.setattr('kamnews.chat_tools.fetch_rss_items', _fake_rss)

    saida = await buscar_noticias('  vale ', ['Vale'], Settings())
    assert 'Vale anuncia resultado' in saida
    assert 'https://exemplo.com/1' in saida


async def test_buscar_noticias_sem_resultado(monkeypatch):
    async def _vazio(company, settings):
        return []

    monkeypatch.setattr('kamnews.chat_tools.fetch_rss_items', _vazio)

    with pytest.raises(ToolError):
        await buscar_noticias('Vale', ['Vale'], Settings())


async def test_executar_tool_desconhecida():
    with pytest.raises(ToolError):
        await executar_tool('Inventada', {}, ['Vale'], Settings())


async def test_executar_tool_busca(monkeypatch):
    async def _fake_rss(company, settings):
        return [{'titulo': 'T', 'fonte': None, 'data': None, 'url': None}]

    monkeypatch.setattr('kamnews.chat_tools.fetch_rss_items', _fake_rss)

    saida, fonte = await executar_tool(
        BuscarNoticias.__name__, {'empresa': 'Vale'}, ['Vale'], Settings()
    )
    assert 'T' in saida
    assert fonte == {'tipo': 'noticias', 'alvo': 'Vale'}


HOST_PUBLICO = 'exemplo.com'
PAGINA_OK = '<html><body><p>Conteúdo da matéria</p></body></html>'
TETO_PEQUENO = 10


@pytest.fixture
def rede_falsa(monkeypatch):
    """Troca a rede por um `MockTransport` e registra cada pedido.

    Só `exemplo.com` conta como público — o resto passa pela guarda real
    sem depender de DNS.
    """

    def instalar(handler):
        pedidos = []

        def _registra(request):
            pedidos.append(str(request.url))
            return handler(request)

        monkeypatch.setattr(
            'kamnews.chat_tools._host_e_publico',
            lambda host: host == HOST_PUBLICO,
        )
        monkeypatch.setattr(
            'kamnews.chat_tools._novo_cliente',
            lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(_registra)
            ),
        )
        return pedidos

    return instalar


async def test_ler_pagina_bloqueia_redirect_para_rede_interna(rede_falsa):
    """Uma página pública não pode levar o servidor à rede interna."""
    pedidos = rede_falsa(
        lambda request: httpx.Response(
            HTTPStatus.FOUND,
            headers={'location': 'http://169.254.169.254/latest/'},
        )
    )

    with pytest.raises(ToolError, match='não permitido'):
        await ler_pagina('https://exemplo.com/isca', Settings())

    assert pedidos == ['https://exemplo.com/isca']


async def test_ler_pagina_segue_redirect_publico(rede_falsa):
    def handler(request):
        if request.url.path == '/antiga':
            return httpx.Response(
                HTTPStatus.MOVED_PERMANENTLY, headers={'location': '/nova'}
            )
        return httpx.Response(HTTPStatus.OK, text=PAGINA_OK)

    pedidos = rede_falsa(handler)

    texto = await ler_pagina('https://exemplo.com/antiga', Settings())

    assert 'Conteúdo da matéria' in texto
    assert pedidos[-1] == 'https://exemplo.com/nova'


async def test_ler_pagina_limita_redirects(rede_falsa):
    pedidos = rede_falsa(
        lambda request: httpx.Response(
            HTTPStatus.FOUND, headers={'location': '/laco'}
        )
    )

    with pytest.raises(ToolError, match='redirecionou'):
        await ler_pagina('https://exemplo.com/laco', Settings())

    assert len(pedidos) == MAX_REDIRECTS + 1


async def test_ler_pagina_recusa_pagina_grande(rede_falsa, monkeypatch):
    monkeypatch.setattr('kamnews.chat_tools.MAX_BYTES', TETO_PEQUENO)
    rede_falsa(lambda request: httpx.Response(HTTPStatus.OK, text=PAGINA_OK))

    with pytest.raises(ToolError, match='grande demais'):
        await ler_pagina('https://exemplo.com/', Settings())


async def test_executar_tool_pagina_bloqueada():
    with pytest.raises(ToolError):
        await executar_tool(
            LerPagina.__name__,
            {'url': 'http://127.0.0.1/'},
            ['Vale'],
            Settings(),
        )
