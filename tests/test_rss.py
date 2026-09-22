from kamnews.news_service import build_rss_url, parse_rss
from kamnews.settings import Settings

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Notícias</title>
  <item>
    <title>Vale anuncia aquisição de mina - Valor Econômico</title>
    <link>https://news.google.com/rss/articles/AAA</link>
    <pubDate>Wed, 30 Jul 2026 12:00:00 GMT</pubDate>
    <source url="https://valor.globo.com">Valor Econômico</source>
  </item>
  <item>
    <title>Vale troca CFO - InfoMoney</title>
    <link>https://news.google.com/rss/articles/BBB</link>
    <pubDate>Tue, 29 Jul 2026 09:30:00 GMT</pubDate>
    <source url="https://infomoney.com.br">InfoMoney</source>
  </item>
</channel></rss>
"""

# Mesma matéria republicada por três veículos + uma notícia distinta.
# O Google News devolve o título como "Manchete - Veículo".
DUPES_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Vale anuncia aquisição de mina - Valor Econômico</title>
    <link>https://news.google.com/rss/articles/AAA</link>
    <pubDate>Wed, 30 Jul 2026 12:00:00 GMT</pubDate>
    <source url="https://valor.globo.com">Valor Econômico</source>
  </item>
  <item>
    <title>Vale anuncia aquisição de mina - InfoMoney</title>
    <link>https://news.google.com/rss/articles/BBB</link>
    <pubDate>Wed, 30 Jul 2026 13:00:00 GMT</pubDate>
    <source url="https://infomoney.com.br">InfoMoney</source>
  </item>
  <item>
    <title>Vale anuncia aquisição de mina - Reuters</title>
    <link>https://news.google.com/rss/articles/CCC</link>
    <pubDate>Wed, 30 Jul 2026 14:00:00 GMT</pubDate>
    <source url="https://reuters.com">Reuters</source>
  </item>
  <item>
    <title>Vale troca CFO - Exame</title>
    <link>https://news.google.com/rss/articles/DDD</link>
    <pubDate>Tue, 29 Jul 2026 09:30:00 GMT</pubDate>
    <source url="https://exame.com">Exame</source>
  </item>
</channel></rss>
"""

# Fontes esperadas no XML de exemplo (evita número mágico nos asserts).
EXPECTED = ('Valor Econômico', 'InfoMoney')
# Matérias distintas dentro de DUPES_RSS.
DISTINCT = ('aquisição de mina', 'troca CFO')


def test_parse_rss_extracts_items():
    items = parse_rss(SAMPLE_RSS, max_items=10)
    assert len(items) == len(EXPECTED)
    assert items[0]['fonte'] == 'Valor Econômico'
    assert items[0]['data'] == '2026-07-30'
    assert items[0]['url'].endswith('AAA')
    assert 'Vale' in items[0]['titulo']


def test_parse_rss_respects_max_items():
    items = parse_rss(SAMPLE_RSS, max_items=1)
    assert len(items) == 1


def test_parse_rss_deduplica_mesma_materia():
    items = parse_rss(DUPES_RSS, max_items=10)
    assert len(items) == len(DISTINCT)
    assert 'aquisição de mina' in items[0]['titulo']
    assert 'troca CFO' in items[1]['titulo']
    # Vence a primeira ocorrência (a mais bem rankeada pelo Google).
    assert items[0]['fonte'] == 'Valor Econômico'


def test_parse_rss_deduplica_antes_de_cortar():
    # Antes, `[:max_items]` gastava as vagas com as duplicatas e a
    # notícia distinta nunca chegava ao modelo.
    items = parse_rss(DUPES_RSS, max_items=2)
    assert len(items) == len(DISTINCT)
    assert 'troca CFO' in items[1]['titulo']


def test_build_rss_url():
    settings = Settings()
    url = build_rss_url('Grupo Boticário', settings)
    assert url.startswith('https://news.google.com/rss/search?q=')
    # Segue a janela configurada, não um número fixo.
    assert f'when%3A{settings.NEWS_WINDOW_DAYS}d' in url
    assert 'hl=pt-BR' in url
    assert 'ceid=BR:pt-BR' in url


def test_build_rss_url_respeita_a_janela():
    settings = Settings(NEWS_WINDOW_DAYS=7)
    assert 'when%3A7d' in build_rss_url('Vale', settings)
