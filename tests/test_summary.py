from datetime import date

import pytest

from kamnews.news_service import (
    MAX_ITEMS_PER_THEME,
    NewsServiceError,
    build_user_prompt,
    normalize_summary,
)

TARGET = 5
PERIODO = (date(2026, 7, 25), date(2026, 8, 9))
ITENS_APOS_FUSAO = 2
UM_ITEM = 1

ITEMS = [
    {
        'titulo': 'Vale anuncia aquisição de mina',
        'fonte': 'Valor Econômico',
        'data': '2026-07-30',
        'url': 'https://news.google.com/rss/articles/AAA',
    },
    {
        'titulo': 'Vale troca CFO',
        'fonte': 'InfoMoney',
        'data': '2026-07-29',
        'url': 'https://news.google.com/rss/articles/BBB',
    },
    {
        'titulo': 'Vale investe em nova planta',
        'fonte': 'Reuters',
        'data': '2026-07-28',
        'url': 'https://news.google.com/rss/articles/CCC',
    },
]

# Candidatos com títulos neutros: não casam com nenhuma palavra-chave,
# então o complemento (`_backfill`) não interfere. Serve para isolar a
# lógica que trata a resposta do modelo.
NEUTRAL = [
    {
        'titulo': f'Vale nota {n}',
        'fonte': 'Fonte',
        'data': '2026-08-01',
        'url': f'https://news.google.com/rss/articles/{n}',
    }
    for n in range(9)
]
THEMES_IN_NEUTRAL = 3

# Candidatos com títulos reais, para exercitar o complemento: um de
# cada tema, mais duas linhas de ruído que devem ficar de fora.
CANDIDATOS = [
    {
        'titulo': 'Vale fecha aquisição de mina em Minas - Valor',
        'fonte': 'Valor',
        'data': '2026-08-20',
        'url': 'https://g/1',
    },
    {
        'titulo': 'Ações da Vale sobem 2% no pregão - Money Times',
        'fonte': 'Money Times',
        'data': '2026-08-19',
        'url': 'https://g/2',
    },
    {
        'titulo': 'Vale nomeia novo diretor de operações - Exame',
        'fonte': 'Exame',
        'data': '2026-08-18',
        'url': 'https://g/3',
    },
    {
        'titulo': 'Vale investe R$ 2 bi em nova planta - Reuters',
        'fonte': 'Reuters',
        'data': '2026-08-17',
        'url': 'https://g/4',
    },
    {
        'titulo': 'CADE aprova operação da Vale sem restrições - InfoMoney',
        'fonte': 'InfoMoney',
        'data': '2026-08-16',
        'url': 'https://g/5',
    },
    {
        'titulo': 'Vale registra lucro de R$ 10 bi no trimestre - Estadão',
        'fonte': 'Estadão',
        'data': '2026-08-15',
        'url': 'https://g/6',
    },
    {
        'titulo': 'Vale sobre o clima: nada de novo - Blog',
        'fonte': 'Blog',
        'data': '2026-08-14',
        'url': 'https://g/7',
    },
]


def _temas_com_ids(ids: list[list[int]], categorias: list[str]) -> dict:
    return {
        'temas': [
            {
                'categoria': categoria,
                'itens': [{'id': i, 'texto': f'Nota {i}'} for i in grupo],
            }
            for categoria, grupo in zip(categorias, ids, strict=True)
        ]
    }


def _total(out: dict) -> int:
    return sum(len(tema['itens']) for tema in out['temas'])


# --------------------------------------------------------------------- #
# Prompt                                                                #
# --------------------------------------------------------------------- #
def test_build_user_prompt_nao_envia_urls():
    prompt = build_user_prompt('Vale', '2026-08-09', ITEMS, TARGET)
    assert 'news.google.com' not in prompt
    assert '"id": 0' in prompt
    assert 'Vale troca CFO' in prompt


def test_build_user_prompt_pede_o_alvo_de_itens():
    prompt = build_user_prompt('Vale', '2026-08-09', ITEMS, TARGET)
    assert f'as {TARGET} notícias MAIS RELEVANTES' in prompt
    assert f'no máximo {MAX_ITEMS_PER_THEME} itens' in prompt


def test_build_user_prompt_informa_o_periodo():
    # O período vai no prompt para o modelo não descrever o intervalo
    # errado no resumo ('último mês' quando a busca foi de 15 dias).
    prompt = build_user_prompt('Vale', '2026-08-09', ITEMS, TARGET, PERIODO)
    assert 'período de 25/07/2026 a 09/08/2026' in prompt


# --------------------------------------------------------------------- #
# Tratamento da resposta do modelo                                      #
# --------------------------------------------------------------------- #
def test_normalize_summary_reanexa_fonte_data_url_pelo_id():
    parsed = {
        'empresa': 'errado',
        'manchetePrincipal': 'Vale compra mina.',
        'resumo': 'Movimento de M&A.',
        'temas': [
            {
                'categoria': 'm_a',
                'itens': [{'id': 0, 'texto': 'Aquisição concluída.'}],
            }
        ],
    }
    out = normalize_summary(parsed, 'Vale', ITEMS, TARGET)
    item = out['temas'][0]['itens'][0]
    assert out['empresa'] == 'Vale'
    assert out['temNoticias'] is True
    assert item['fonte'] == 'Valor Econômico'
    assert item['data'] == '2026-07-30'
    assert item['url'].endswith('AAA')


def test_normalize_summary_descarta_lixo_do_modelo():
    parsed = {
        'temas': [
            {'categoria': 'inventada', 'itens': [{'id': 0, 'texto': 'x'}]},
            {'categoria': 'm_a', 'itens': [{'id': 99, 'texto': ''}]},
            {'categoria': 'lideranca', 'itens': 'não é lista'},
        ]
    }
    out = normalize_summary(parsed, 'Vale', NEUTRAL, TARGET)
    assert out['temas'] == []
    assert out['temNoticias'] is False


def test_normalize_summary_limita_itens_por_tema():
    itens = [{'id': i, 'texto': f'Nota {i}'} for i in range(len(NEUTRAL))]
    parsed = {'temas': [{'categoria': 'lideranca', 'itens': itens}]}
    out = normalize_summary(parsed, 'Vale', NEUTRAL, TARGET)
    assert len(out['temas'][0]['itens']) == MAX_ITEMS_PER_THEME


def test_normalize_summary_um_tema_so_nao_trava_abaixo_do_teto():
    # Empresa cujas notícias do mês caem todas no mesmo tema: entrega
    # MAX_ITEMS_PER_THEME itens em vez de parar em 3.
    itens = [{'id': i, 'texto': f'Nota {i}'} for i in range(len(NEUTRAL))]
    parsed = {
        'temas': [{'categoria': 'resultados_financeiros', 'itens': itens}]
    }
    out = normalize_summary(parsed, 'Vale', NEUTRAL, TARGET)
    assert _total(out) == MAX_ITEMS_PER_THEME


def test_normalize_summary_limita_o_total_no_alvo():
    parsed = _temas_com_ids(
        [[0, 1, 2], [3, 4, 5], [6, 7, 8]],
        ['resultados_financeiros', 'm_a', 'expansao'],
    )
    out = normalize_summary(parsed, 'Vale', NEUTRAL, TARGET)
    assert _total(out) == TARGET
    # Round-robin: o alvo é distribuído, não consumido por um tema só.
    assert len(out['temas']) == THEMES_IN_NEUTRAL


@pytest.mark.parametrize(
    ('bruta', 'esperada'),
    [
        ('Resultados Financeiros', 'resultados_financeiros'),
        ('resultados', 'resultados_financeiros'),
        ('M&A', 'm_a'),
        ('Fusões e Aquisições', 'm_a'),
        ('Expansão', 'expansao'),
        ('Liderança', 'lideranca'),
        ('regulação', 'regulatorio'),
    ],
)
def test_normalize_summary_aceita_variacao_de_categoria(bruta, esperada):
    parsed = {
        'temas': [{'categoria': bruta, 'itens': [{'id': 0, 'texto': 'Fato.'}]}]
    }
    out = normalize_summary(parsed, 'Vale', NEUTRAL, TARGET)
    assert [t['categoria'] for t in out['temas']] == [esperada]


def test_normalize_summary_junta_categoria_repetida():
    parsed = _temas_com_ids([[0], [1]], ['m_a', 'm_a'])
    out = normalize_summary(parsed, 'Vale', NEUTRAL, TARGET)
    assert len(out['temas']) == UM_ITEM
    assert len(out['temas'][0]['itens']) == ITENS_APOS_FUSAO


def test_normalize_summary_nao_repete_a_mesma_noticia_em_dois_temas():
    parsed = _temas_com_ids([[0], [0]], ['m_a', 'expansao'])
    out = normalize_summary(parsed, 'Vale', NEUTRAL, TARGET)
    assert _total(out) == UM_ITEM


def test_normalize_summary_rejeita_resposta_fora_do_formato():
    # Modelos pequenos às vezes ecoam um item solto do RSS.
    with pytest.raises(NewsServiceError):
        normalize_summary(ITEMS[0]['titulo'], 'Vale', ITEMS, TARGET)


# --------------------------------------------------------------------- #
# Complemento com os candidatos menos relevantes (_backfill)             #
# --------------------------------------------------------------------- #
def test_backfill_completa_ate_o_alvo():
    # O modelo devolveu 1 item; o resto vem da fila do RSS.
    parsed = {
        'temas': [
            {
                'categoria': 'm_a',
                'itens': [{'id': 0, 'texto': 'Aquisição fechada.'}],
            }
        ]
    }
    out = normalize_summary(parsed, 'Vale', CANDIDATOS, TARGET)
    assert _total(out) == TARGET
    assert out['temNoticias'] is True


def test_backfill_preserva_o_resumo_do_modelo():
    parsed = {
        'temas': [
            {
                'categoria': 'm_a',
                'itens': [{'id': 0, 'texto': 'Aquisição fechada.'}],
            }
        ]
    }
    out = normalize_summary(parsed, 'Vale', CANDIDATOS, TARGET)
    ma = next(t for t in out['temas'] if t['categoria'] == 'm_a')
    assert ma['itens'][0]['texto'] == 'Aquisição fechada.'
    assert ma['itens'][0]['url'] == 'https://g/1'


def test_backfill_classifica_por_palavra_chave():
    out = normalize_summary({'temas': []}, 'Vale', CANDIDATOS, TARGET)
    achados = {
        t['categoria']: [i['texto'] for i in t['itens']] for t in out['temas']
    }
    assert 'Vale nomeia novo diretor de operações' in achados['lideranca']
    assert (
        'CADE aprova operação da Vale sem restrições'
        in (achados['regulatorio'])
    )
    assert 'Vale investe R$ 2 bi em nova planta' in achados['expansao']


def test_backfill_remove_o_sufixo_do_veiculo():
    out = normalize_summary({'temas': []}, 'Vale', CANDIDATOS, TARGET)
    for tema in out['temas']:
        for item in tema['itens']:
            assert not item['texto'].endswith(f' - {item["fonte"]}')


def test_backfill_descarta_ruido_de_mercado():
    out = normalize_summary({'temas': []}, 'Vale', CANDIDATOS, TARGET)
    textos = [i['texto'] for t in out['temas'] for i in t['itens']]
    assert not any('pregão' in texto for texto in textos)
    assert not any('clima' in texto for texto in textos)


def test_backfill_nao_duplica_item_ja_escolhido():
    parsed = _temas_com_ids([[0]], ['m_a'])
    out = normalize_summary(parsed, 'Vale', CANDIDATOS, TARGET)
    urls = [i['url'] for t in out['temas'] for i in t['itens']]
    assert len(urls) == len(set(urls))


def test_backfill_nao_dispara_quando_o_alvo_ja_foi_atingido():
    parsed = _temas_com_ids(
        [[0, 1, 2], [3, 4]], ['resultados_financeiros', 'm_a']
    )
    out = normalize_summary(parsed, 'Vale', CANDIDATOS, TARGET)
    assert _total(out) == TARGET
    textos = [i['texto'] for t in out['temas'] for i in t['itens']]
    # Todos os textos continuam sendo os do modelo ('Nota N').
    assert all(texto.startswith('Nota ') for texto in textos)


def test_backfill_respeita_o_teto_por_tema():
    # Só notícias de um tema disponíveis: não estoura o teto do tema.
    so_lideranca = [
        {
            'titulo': f'Vale nomeia diretor {n}',
            'fonte': 'Exame',
            'data': '2026-08-01',
            'url': f'https://g/l{n}',
        }
        for n in range(TARGET + MAX_ITEMS_PER_THEME)
    ]
    out = normalize_summary({'temas': []}, 'Vale', so_lideranca, TARGET)
    assert len(out['temas']) == UM_ITEM
    assert _total(out) == MAX_ITEMS_PER_THEME
