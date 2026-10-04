"""Ferramentas de internet do assistente: RSS e leitura de página.

O modelo decide quando usá-las, mas quem decide o que é permitido é este
módulo: busca só para clientes da carteira, e leitura só de endereços
públicos.
"""

import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from kamnews.news_service import fetch_rss_items
from kamnews.settings import Settings

PAGINA_TIMEOUT = 15
MAX_BYTES = 1_500_000
MAX_REDIRECTS = 5
USER_AGENT = 'Mozilla/5.0 (KAM News Digest)'
RSS_NO_CONTEXTO = 8

TAGS_IGNORADAS = ('script', 'style', 'noscript', 'header', 'footer', 'nav')


class BuscarNoticias(BaseModel):
    """Busca notícias recentes na internet sobre um cliente da carteira.

    Use quando a pergunta pedir novidades que podem não estar nas
    notícias já salvas.
    """

    empresa: str = Field(
        description='Nome do cliente, exatamente como consta na carteira.'
    )


class LerPagina(BaseModel):
    """Lê o conteúdo de uma página web.

    Use para aprofundar em uma notícia específica cujo link apareça no
    contexto ou na pergunta.
    """

    url: str = Field(description='URL http(s) completa da página.')


class ToolError(Exception):
    """Erro tratável de ferramenta — vira texto de volta para o modelo."""


def _host_e_publico(host: str) -> bool:
    """Bloqueia loopback, rede privada, link-local e reservados.

    Sem isto, o modelo poderia fazer o servidor buscar o Postgres, o
    Ollama ou o metadata da nuvem. A resolução é feita aqui e a checagem
    vale para o momento da consulta — não protege contra DNS rebinding,
    o que é aceitável para uma ferramenta interna e autenticada.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False

    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def validar_url(url: str) -> str:
    partes = urlparse(url)
    if partes.scheme not in {'http', 'https'} or not partes.hostname:
        raise ToolError('URL inválida: use um endereço http(s) completo.')
    if not _host_e_publico(partes.hostname):
        raise ToolError('Endereço não permitido.')
    return url


def extrair_texto(
    html: str | bytes, limite: int, encoding: str | None = None
) -> str:
    sopa = BeautifulSoup(html, 'html.parser', from_encoding=encoding)
    for tag in sopa(list(TAGS_IGNORADAS)):
        tag.decompose()

    texto = ' '.join(sopa.get_text(' ', strip=True).split())
    if len(texto) > limite:
        texto = texto[:limite] + '…'
    return texto


def _novo_cliente() -> httpx.AsyncClient:
    """Sem `follow_redirects`: quem segue é `_baixar`, validando cada
    salto. Os testes substituem esta função por um transporte falso."""
    return httpx.AsyncClient(
        timeout=PAGINA_TIMEOUT,
        follow_redirects=False,
        headers={'User-Agent': USER_AGENT},
    )


async def _ler_corpo(resposta: httpx.Response) -> bytes:
    """Lê em pedaços e para no teto, sem carregar a página inteira."""
    corpo = bytearray()
    async for pedaco in resposta.aiter_bytes():
        corpo.extend(pedaco)
        if len(corpo) > MAX_BYTES:
            raise ToolError('Página grande demais para ser lida.')
    return bytes(corpo)


async def _baixar(url: str) -> tuple[bytes, str | None]:
    """Segue redirects à mão, passando cada destino pela guarda de SSRF.

    Com o `follow_redirects` do httpx, só a primeira URL era validada:
    uma página pública respondendo `302 Location: http://ollama:11434/`
    levava o servidor à rede interna.
    """
    async with _novo_cliente() as client:
        for _ in range(MAX_REDIRECTS + 1):
            validar_url(url)
            async with client.stream('GET', url) as resposta:
                if resposta.is_redirect:
                    destino = resposta.headers.get('location', '')
                    url = str(resposta.url.join(destino))
                    continue
                resposta.raise_for_status()
                corpo = await _ler_corpo(resposta)
                return corpo, resposta.charset_encoding
    raise ToolError('A página redirecionou vezes demais.')


async def ler_pagina(url: str, settings: Settings) -> str:
    try:
        corpo, encoding = await _baixar(url)
    except httpx.HTTPError as err:
        raise ToolError(f'Não foi possível abrir a página: {err}') from err

    texto = extrair_texto(corpo, settings.CHAT_MAX_PAGINA_CHARS, encoding)
    if not texto:
        raise ToolError('A página não trouxe texto legível.')
    return texto


async def buscar_noticias(
    empresa: str, permitidas: list[str], settings: Settings
) -> str:
    """Só busca para clientes da carteira — é a fronteira de escopo."""
    alvo = next(
        (p for p in permitidas if p.casefold() == empresa.strip().casefold()),
        None,
    )
    if alvo is None:
        raise ToolError(
            f'"{empresa}" não é um cliente desta carteira. '
            f'Clientes disponíveis: {", ".join(permitidas) or "nenhum"}.'
        )

    itens = await fetch_rss_items(alvo, settings)
    if not itens:
        raise ToolError(f'Nenhuma notícia recente encontrada para {alvo}.')

    linhas = [f'NOTÍCIAS RECENTES NA INTERNET SOBRE {alvo}:']
    for item in itens[:RSS_NO_CONTEXTO]:
        partes = [item.get('titulo') or '']
        if item.get('fonte'):
            partes.append(f'fonte: {item["fonte"]}')
        if item.get('data'):
            partes.append(item['data'])
        linhas.append('- ' + ' | '.join(p for p in partes if p))
        if item.get('url'):
            linhas.append(f'  url: {item["url"]}')
    return '\n'.join(linhas)
