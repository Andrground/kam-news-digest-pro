import asyncio
import json
import re
import unicodedata
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from pathlib import Path
from string import Template
from urllib.parse import quote_plus
from xml.etree import ElementTree

import httpx

from kamnews.settings import Settings, get_settings, hoje_br

SYSTEM = (
    'Você é um analista sênior de inteligência de mercado que prepara '
    'briefings diários para Key Account Managers no Brasil. Você organiza, '
    'em português, apenas notícias reais fornecidas, sem inventar nada. '
    'Responda sempre com um único objeto JSON válido.'
)

MAX_ATTEMPTS = 3
# Período de busca: (data inicial, data final), ambas inclusivas.
Periodo = tuple[date, date]
UM_DIA = timedelta(days=1)
HTTP_TIMEOUT = 20
USER_AGENT = 'Mozilla/5.0 (KAM News Digest)'
# Teto por tema. Fica abaixo de NEWS_TARGET_ITEMS de propósito: garante
# que um briefing cheio cubra pelo menos dois temas, sem travar em 3 as
# empresas cujas notícias do mês caem todas no mesmo tema.
MAX_ITEMS_PER_THEME = 4
CATEGORIES = frozenset({
    'resultados_financeiros',
    'm_a',
    'expansao',
    'lideranca',
    'regulatorio',
})

# Modelos pequenos escrevem a categoria com outro nome ('resultados',
# 'M&A', 'fusões e aquisições'). Sem esse mapa o tema inteiro era
# descartado em silêncio — a maior causa de briefing vazio.
CATEGORY_ALIASES = {
    'resultados': 'resultados_financeiros',
    'resultado': 'resultados_financeiros',
    'resultado_financeiro': 'resultados_financeiros',
    'resultados_financeiro': 'resultados_financeiros',
    'financeiro': 'resultados_financeiros',
    'financeiros': 'resultados_financeiros',
    'financas': 'resultados_financeiros',
    'balanco': 'resultados_financeiros',
    'ma': 'm_a',
    'm_e_a': 'm_a',
    'fusoes': 'm_a',
    'aquisicoes': 'm_a',
    'fusoes_e_aquisicoes': 'm_a',
    'expansoes': 'expansao',
    'investimento': 'expansao',
    'investimentos': 'expansao',
    'liderancas': 'lideranca',
    'gestao': 'lideranca',
    'governanca': 'lideranca',
    'regulacao': 'regulatorio',
    'regulatorios': 'regulatorio',
    'compliance': 'regulatorio',
}


# Classificação por palavra-chave, usada só no complemento: quando o
# modelo devolve menos que NEWS_TARGET_ITEMS, os itens restantes do RSS
# entram por aqui. A ordem importa — o primeiro tema que casar vence,
# então os sinais mais específicos (cargo, órgão regulador) vêm antes.
FALLBACK_KEYWORDS = (
    (
        'lideranca',
        (
            'ceo',
            'cfo',
            'coo',
            'cio',
            'presidente',
            'presidencia',
            'diretor',
            'diretora',
            'diretoria',
            'conselho',
            'executivo',
            'executiva',
            'nomeia',
            'nomeado',
            'assume',
            'renuncia',
            'sucessao',
            'comando',
        ),
    ),
    (
        'm_a',
        (
            'aquisicao',
            'aquisicoes',
            'adquire',
            'adquiriu',
            'compra',
            'comprar',
            'fusao',
            'fusoes',
            'vende',
            'vender',
            'venda',
            'participacao',
            'fatia',
            'incorpora',
            'joint',
            'controle',
            'desinvestimento',
        ),
    ),
    (
        'regulatorio',
        (
            'cade',
            'cvm',
            'aneel',
            'ans',
            'anvisa',
            'anatel',
            'antaq',
            'multa',
            'multado',
            'processo',
            'justica',
            'stf',
            'stj',
            'liminar',
            'antidumping',
            'tarifa',
            'imposto',
            'tributario',
            'compliance',
            'investigacao',
            'condenada',
            'acordo',
        ),
    ),
    (
        'expansao',
        (
            'fabrica',
            'planta',
            'investimento',
            'investimentos',
            'investe',
            'investir',
            'expansao',
            'expande',
            'amplia',
            'ampliar',
            'capacidade',
            'inaugura',
            'inauguracao',
            'obra',
            'unidade',
            'contratacoes',
            'contratar',
            'exportacao',
            'parceria',
            'lanca',
            'projeto',
        ),
    ),
    (
        'resultados_financeiros',
        (
            'lucro',
            'prejuizo',
            'receita',
            'balanco',
            'resultado',
            'resultados',
            'trimestre',
            'trimestral',
            'ebitda',
            'guidance',
            'faturamento',
            'dividendo',
            'dividendos',
            'endividamento',
            'divida',
        ),
    ),
)

# Ruído de mercado que nunca deve entrar no briefing pelo complemento.
NOISE_KEYWORDS = frozenset({
    'ibovespa',
    'pregao',
    'fechamento',
    'cotacao',
    'radar',
    'sobem',
    'caem',
    'sobe',
    'cai',
    'dispara',
    'derrete',
    'recomendacao',
    'analise',
    'carteira',
    'dicas',
    'melhores',
})


def _slug(value: str) -> str:
    """Normaliza texto para comparação: minúsculas, sem acento, com `_`.

    'Expansão' -> 'expansao'; 'M&A' -> 'm_a'.
    """
    norm = unicodedata.normalize('NFKD', value.lower())
    norm = ''.join(c for c in norm if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '_', norm).strip('_')


_PROMPT = Template(
    (Path(__file__).parent / 'prompts' / 'company_news.txt').read_text(
        encoding='utf-8'
    )
)


class NewsServiceError(Exception):
    """Erro tratável na busca/parse das notícias."""


# --------------------------------------------------------------------------- #
# Google News RSS (busca gratuita)                                            #
# --------------------------------------------------------------------------- #
def build_rss_url(
    company: str, settings: Settings, periodo: Periodo | None = None
) -> str:
    """URL da busca. Sem período, cobre os últimos `NEWS_WINDOW_DAYS`.

    Com período, usa `after:`/`before:`, que são exclusivos no Google:
    a margem de um dia de cada lado mantém as duas pontas no resultado.
    """
    if periodo is None:
        filtro = f'when:{settings.NEWS_WINDOW_DAYS}d'
    else:
        inicio, fim = periodo
        filtro = (
            f'after:{(inicio - UM_DIA).isoformat()} '
            f'before:{(fim + UM_DIA).isoformat()}'
        )
    query = quote_plus(f'{company} {filtro}')
    return (
        'https://news.google.com/rss/search'
        f'?q={query}&hl={settings.NEWS_HL}'
        f'&gl={settings.NEWS_GL}&ceid={settings.NEWS_CEID}'
    )


def _format_date(pub: str | None) -> str | None:
    if not pub:
        return None
    try:
        return parsedate_to_datetime(pub).date().isoformat()
    except (TypeError, ValueError):
        return None


def _dedup_key(titulo: str) -> str:
    """Chave da matéria: título sem o sufixo ' - Veículo' do Google."""
    base = titulo.rsplit(' - ', 1)[0] if ' - ' in titulo else titulo
    return _slug(base)


def parse_rss(xml_text: str, max_items: int) -> list[dict]:
    """Extrai os itens do RSS, descartando a mesma matéria repetida.

    O Google News devolve até 100 itens por busca, já na ordem de
    relevância dele, e repete a mesma notícia publicada por veículos
    diferentes. Varremos o feed inteiro, tiramos as repetições e só
    então cortamos em `max_items` — antes as duplicatas gastavam as
    vagas e sobrava pouca notícia distinta para o modelo classificar.
    """
    root = ElementTree.fromstring(xml_text)
    items = []
    seen = set()
    for node in root.iterfind('.//item'):
        titulo = (node.findtext('title') or '').strip()
        if not titulo:
            continue
        chave = _dedup_key(titulo)
        if chave in seen:
            continue
        seen.add(chave)
        source = node.find('source')
        fonte = (
            source.text.strip() if source is not None and source.text else None
        )
        items.append({
            'titulo': titulo,
            'fonte': fonte,
            'data': _format_date(node.findtext('pubDate')),
            'url': (node.findtext('link') or '').strip() or None,
        })
        if len(items) >= max_items:
            break
    return items


async def fetch_rss_items(
    company: str, settings: Settings, periodo: Periodo | None = None
) -> list[dict]:
    url = build_rss_url(company, settings, periodo)
    last_err = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT,
                follow_redirects=True,
                headers={'User-Agent': USER_AGENT},
            ) as http:
                resp = await http.get(url)
                resp.raise_for_status()
            return parse_rss(resp.text, settings.NEWS_MAX_ITEMS)
        except httpx.HTTPError as err:
            last_err = err
            if attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
            raise NewsServiceError('Falha ao buscar no Google News.') from err
    raise NewsServiceError('Falha ao buscar no Google News.') from last_err


# --------------------------------------------------------------------------- #
# Resumo/classificação via Ollama (modelo local)                             #
# --------------------------------------------------------------------------- #
def build_user_prompt(
    company: str,
    date_str: str,
    items: list[dict],
    target: int | None = None,
    periodo: Periodo | None = None,
) -> str:
    """Monta o prompt com itens enxutos (só id + título).

    Fonte, data e URL ficam fora: o modelo devolve apenas o `id` e o
    serviço reanexa os campos originais. As URLs do Google News têm
    200+ caracteres em base64 — mandá-las ao modelo estoura a janela de
    contexto e multiplica o tempo de geração.

    `target` é a quantidade de notícias pedida no briefing final e
    `periodo` o intervalo coberto pela busca; os padrões vêm de
    `NEWS_TARGET_ITEMS` e dos últimos `NEWS_WINDOW_DAYS`. O período
    entra no prompt para o modelo não descrever o intervalo errado.
    """
    settings = get_settings()
    alvo = target if target is not None else settings.NEWS_TARGET_ITEMS
    if periodo is None:
        hoje = hoje_br()
        periodo = (hoje - timedelta(days=settings.NEWS_WINDOW_DAYS), hoje)
    inicio, fim = periodo
    base = _PROMPT.substitute(
        company=company,
        date_str=date_str,
        target_items=alvo,
        max_per_theme=MAX_ITEMS_PER_THEME,
        data_inicio=inicio.strftime('%d/%m/%Y'),
        data_fim=fim.strftime('%d/%m/%Y'),
    )
    slim = [
        {'id': idx, 'titulo': item['titulo'], 'fonte': item['fonte']}
        for idx, item in enumerate(items)
    ]
    items_json = json.dumps(slim, ensure_ascii=False, indent=2)
    return f'{base}\n\nLISTA DE NOTÍCIAS (JSON):\n{items_json}'


def extract_json(text: str | None) -> dict | None:
    if not text:
        return None
    cleaned = text.replace('```json', '').replace('```', '').strip()
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None


async def _call_ollama(prompt: str, settings: Settings) -> str:
    url = f'{settings.OLLAMA_HOST}/api/chat'
    payload = {
        'model': settings.OLLAMA_MODEL,
        'messages': [
            {'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': prompt},
        ],
        'stream': False,
        'format': 'json',
        'options': {
            'temperature': 0.2,
            'num_predict': settings.OLLAMA_NUM_PREDICT,
            'num_ctx': settings.OLLAMA_NUM_CTX,
        },
    }
    last_err = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            async with httpx.AsyncClient(
                timeout=settings.OLLAMA_TIMEOUT
            ) as http:
                resp = await http.post(url, json=payload)
                resp.raise_for_status()
            return resp.json().get('message', {}).get('content', '')
        except httpx.TimeoutException as err:
            # Não repetir: cada tentativa custa OLLAMA_TIMEOUT inteiro.
            raise NewsServiceError(
                f'O modelo "{settings.OLLAMA_MODEL}" demorou mais de '
                f'{settings.OLLAMA_TIMEOUT}s para responder. Tente um '
                'modelo menor ou reduza NEWS_MAX_ITEMS.'
            ) from err
        except httpx.ConnectError as err:
            raise NewsServiceError(
                f'Não consegui conectar ao Ollama em {settings.OLLAMA_HOST}. '
                'Ele está rodando? (ollama serve)'
            ) from err
        except httpx.HTTPStatusError as err:
            if err.response.status_code == HTTPStatus.NOT_FOUND:
                raise NewsServiceError(
                    f'Modelo "{settings.OLLAMA_MODEL}" não encontrado no '
                    f'Ollama. Rode: ollama pull {settings.OLLAMA_MODEL}'
                ) from err
            last_err = err
            if attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
            raise NewsServiceError('Falha ao chamar o Ollama.') from err
        except httpx.HTTPError as err:
            last_err = err
            if attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
            raise NewsServiceError('Falha ao chamar o Ollama.') from err
    raise NewsServiceError('Falha ao chamar o Ollama.') from last_err


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _origin(entry: dict, items: list[dict]) -> dict:
    """Recupera o item original do RSS pelo `id` devolvido pelo modelo."""
    try:
        idx = int(entry.get('id'))
    except (TypeError, ValueError):
        return {}
    if 0 <= idx < len(items):
        return items[idx]
    return {}


def _clean_items(raw: object, items: list[dict]) -> list[dict]:
    cleaned = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        texto = _text(entry.get('texto'))
        if not texto:
            continue
        origem = _origin(entry, items)
        cleaned.append({
            'texto': texto,
            'fonte': origem.get('fonte') or _text(entry.get('fonte')),
            'data': origem.get('data') or _text(entry.get('data')),
            'url': origem.get('url'),
        })
    return cleaned[:MAX_ITEMS_PER_THEME]


def _categoria(value: object) -> str | None:
    """Resolve a categoria devolvida pelo modelo para o nome canônico."""
    texto = _text(value)
    if not texto:
        return None
    slug = _slug(texto)
    if slug in CATEGORIES:
        return slug
    return CATEGORY_ALIASES.get(slug)


def _merge_temas(temas: list[dict]) -> list[dict]:
    """Junta temas repetidos, preservando a ordem de aparição.

    O frontend localiza cada categoria com `find`, então um segundo
    tema com a mesma categoria nunca chegaria à tela.
    """
    merged: dict[str, dict] = {}
    for tema in temas:
        alvo = merged.get(tema['categoria'])
        if alvo is None:
            merged[tema['categoria']] = dict(tema)
            continue
        alvo['itens'] = (alvo['itens'] + tema['itens'])[:MAX_ITEMS_PER_THEME]
    return list(merged.values())


def _trim_total(temas: list[dict], limit: int) -> list[dict]:
    """Limita o total de itens do briefing, alternando entre os temas.

    Round-robin em vez de corte sequencial: assim um tema com 3 itens
    não ocupa todas as vagas e o briefing mostra assuntos variados.
    A mesma notícia classificada em dois temas conta uma vez só.
    """
    escolhidos: list[list[dict]] = [[] for _ in temas]
    vistos: set[str] = set()
    total = 0
    for rodada in range(MAX_ITEMS_PER_THEME):
        for idx, tema in enumerate(temas):
            if total >= limit:
                break
            if rodada >= len(tema['itens']):
                continue
            item = tema['itens'][rodada]
            chave = item['url'] or _slug(item['texto'])
            if chave in vistos:
                continue
            vistos.add(chave)
            escolhidos[idx].append(item)
            total += 1
        if total >= limit:
            break
    return [
        {'categoria': tema['categoria'], 'itens': escolhidos[idx]}
        for idx, tema in enumerate(temas)
        if escolhidos[idx]
    ]


def _tem_palavra(slug: str, palavra: str) -> bool:
    """Casa palavra inteira dentro do slug (que usa `_` como separador)."""
    return f'_{palavra}_' in f'_{slug}_'


def _guess_categoria(titulo: str) -> str | None:
    """Classifica um título do RSS por palavra-chave.

    Só para o complemento — a classificação boa é a do modelo. Devolve
    `None` para o que é ruído de mercado ou não casa com nenhum tema,
    porque não há como enquadrar o item sem inventar.
    """
    slug = _slug(titulo)
    if any(_tem_palavra(slug, ruido) for ruido in NOISE_KEYWORDS):
        return None
    for categoria, palavras in FALLBACK_KEYWORDS:
        if any(_tem_palavra(slug, palavra) for palavra in palavras):
            return categoria
    return None


def _titulo_limpo(item: dict) -> str:
    """Título sem o sufixo ' - Veículo' (a fonte já vai em `fonte`)."""
    titulo = item['titulo']
    fonte = item.get('fonte')
    sufixo = f' - {fonte}'
    if fonte and titulo.endswith(sufixo):
        return titulo[: -len(sufixo)].strip() or titulo
    return titulo


def _backfill(temas: list[dict], items: list[dict], limit: int) -> list[dict]:
    """Completa o briefing com as notícias que o modelo não escolheu.

    Modelos pequenos devolvem menos itens que o alvo. Os candidatos
    restantes já estão na ordem de relevância do Google, então pegamos
    os próximos da fila e classificamos por palavra-chave. O texto é o
    próprio título do RSS — segue valendo a regra anti-alucinação: nada
    aqui é inventado, só reaproveitado.
    """
    total = sum(len(tema['itens']) for tema in temas)
    if total >= limit:
        return temas
    usados = {
        item['url'] for tema in temas for item in tema['itens'] if item['url']
    }
    por_categoria = {tema['categoria']: tema for tema in temas}
    for item in items:
        if total >= limit:
            break
        if not item['url'] or item['url'] in usados:
            continue
        categoria = _guess_categoria(item['titulo'])
        if categoria is None:
            continue
        tema = por_categoria.get(categoria)
        if tema is None:
            tema = {'categoria': categoria, 'itens': []}
            por_categoria[categoria] = tema
            temas.append(tema)
        if len(tema['itens']) >= MAX_ITEMS_PER_THEME:
            continue
        tema['itens'].append({
            'texto': _titulo_limpo(item),
            'fonte': item['fonte'],
            'data': item['data'],
            'url': item['url'],
        })
        usados.add(item['url'])
        total += 1
    return temas


def normalize_summary(
    parsed: object,
    company: str,
    items: list[dict],
    target: int | None = None,
) -> dict:
    """Converte a saída livre do modelo no formato de `CompanyNews`.

    Modelos pequenos às vezes devolvem outro formato (um item solto, por
    exemplo). Aqui a resposta é coagida ao schema e o que não encaixa é
    descartado — nunca vaza para o `response_model`. O total de itens é
    limitado a `target` (padrão: `NEWS_TARGET_ITEMS`) e, se o modelo
    devolver menos que isso, completado com os candidatos que ele não
    escolheu (ver `_backfill`).
    """
    if not isinstance(parsed, dict):
        raise NewsServiceError(
            'Não foi possível interpretar a resposta do modelo.'
        )
    limite = target if target is not None else get_settings().NEWS_TARGET_ITEMS
    temas = []
    for tema in parsed.get('temas') or []:
        if not isinstance(tema, dict):
            continue
        categoria = _categoria(tema.get('categoria'))
        tema_itens = _clean_items(tema.get('itens'), items)
        if categoria and tema_itens:
            temas.append({'categoria': categoria, 'itens': tema_itens})
    temas = _backfill(_trim_total(_merge_temas(temas), limite), items, limite)
    return {
        'empresa': company,
        'temNoticias': bool(temas),
        'manchetePrincipal': _text(parsed.get('manchetePrincipal')),
        'resumo': _text(parsed.get('resumo')),
        'temas': temas,
    }


async def _summarize(
    company: str,
    date_str: str,
    items: list[dict],
    settings: Settings,
    periodo: Periodo | None,
) -> dict:
    prompt = build_user_prompt(
        company, date_str, items, settings.NEWS_TARGET_ITEMS, periodo
    )
    content = await _call_ollama(prompt, settings)
    parsed = extract_json(content)
    if not parsed:
        raise NewsServiceError(
            'Não foi possível interpretar a resposta do modelo.'
        )
    return normalize_summary(
        parsed, company, items, settings.NEWS_TARGET_ITEMS
    )


def _empty(company: str) -> dict:
    return {
        'empresa': company,
        'temNoticias': False,
        'manchetePrincipal': None,
        'resumo': None,
        'temas': [],
    }


async def fetch_company_news(
    company: str, date_str: str, periodo: Periodo | None = None
) -> dict:
    settings = get_settings()
    items = await fetch_rss_items(company, settings, periodo)
    if not items:
        return _empty(company)
    return await _summarize(company, date_str, items, settings, periodo)
