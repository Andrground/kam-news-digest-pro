from datetime import date
from http import HTTPStatus

from sqlalchemy import func, select

from kamnews.app import app
from kamnews.models import Noticia
from kamnews.noticias_service import url_hash
from kamnews.routers.news import get_news_fetcher
from tests.conftest import auth

URL_HASH_LEN = 64
DOIS_DONOS = 2


def _buscar(client, token, key_account):
    return client.post(
        '/news/',
        json={
            'company': key_account.nome,
            'key_account_id': key_account.id,
        },
        headers=auth(token),
    )


def _total(session):
    return session.scalar(select(func.count()).select_from(Noticia))


def _primeiro_id(response):
    return response.json()['temas'][0]['itens'][0]['id']


def _fetcher(texto='Aquisição concluída.', url='https://exemplo.com'):
    """Stub com texto/URL controlados, para os casos de dedup."""

    async def _fake(company, date_str, periodo):
        return {
            'empresa': company,
            'temNoticias': True,
            'manchetePrincipal': None,
            'resumo': None,
            'temas': [
                {
                    'categoria': 'm_a',
                    'itens': [
                        {
                            'texto': texto,
                            'fonte': 'Valor',
                            'data': '2026-01-01',
                            'url': url,
                        }
                    ],
                }
            ],
        }

    return _fake


# --------------------------------------------------------------------- #
# Persistência
# --------------------------------------------------------------------- #
def test_busca_persiste_noticia(
    client, fake_news, kam_token, key_account, session
):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    response = _buscar(client, kam_token, key_account)
    assert response.status_code == HTTPStatus.OK

    noticia = session.scalar(select(Noticia))
    assert noticia is not None
    assert noticia.key_account_id == key_account.id
    assert noticia.texto == 'Aquisição concluída.'
    assert noticia.categoria == 'm_a'
    assert noticia.fonte == 'Valor'
    assert noticia.url == 'https://exemplo.com'
    assert noticia.data_publicacao == date(2026, 1, 1)
    assert noticia.avaliacao is None


def test_resposta_traz_id_da_noticia(
    client, fake_news, kam_token, key_account
):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    item = _buscar(client, kam_token, key_account).json()['temas'][0]['itens'][
        0
    ]
    assert isinstance(item['id'], int)
    assert item['avaliacao'] is None


def test_rebuscar_nao_duplica(
    client, fake_news, kam_token, key_account, session
):
    """A mesma URL na mesma key account reaproveita a linha."""
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news

    primeira = _buscar(client, kam_token, key_account)
    segunda = _buscar(client, kam_token, key_account)

    assert _total(session) == 1
    assert _primeiro_id(primeira) == _primeiro_id(segunda)


def test_rebuscar_preserva_avaliacao(
    client, fake_news, kam_token, key_account
):
    """É o motivo de existir o dedup: o like não some na próxima busca."""
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news

    noticia_id = _primeiro_id(_buscar(client, kam_token, key_account))
    client.put(
        f'/noticias/{noticia_id}/avaliacao/',
        json={'valor': 'like'},
        headers=auth(kam_token),
    )

    item = _buscar(client, kam_token, key_account).json()['temas'][0]['itens'][
        0
    ]
    assert item['id'] == noticia_id
    assert item['avaliacao'] == 'like'


def test_rebuscar_atualiza_texto_sem_perder_avaliacao(
    client, kam_token, key_account, session
):
    """O modelo reescreve o bullet entre buscas; a avaliação fica."""
    app.dependency_overrides[get_news_fetcher] = lambda: _fetcher('Versão 1')
    noticia_id = _primeiro_id(_buscar(client, kam_token, key_account))
    client.put(
        f'/noticias/{noticia_id}/avaliacao/',
        json={'valor': 'dislike'},
        headers=auth(kam_token),
    )

    app.dependency_overrides[get_news_fetcher] = lambda: _fetcher('Versão 2')
    item = _buscar(client, kam_token, key_account).json()['temas'][0]['itens'][
        0
    ]

    assert _total(session) == 1
    assert item['id'] == noticia_id
    assert item['avaliacao'] == 'dislike'

    noticia = session.scalar(select(Noticia))
    session.refresh(noticia)
    assert noticia.texto == 'Versão 2'


def test_key_accounts_diferentes_nao_compartilham_noticia(
    client, kam_token, other_kam_token, key_account, session
):
    """Mesmo nome e mesma URL, donos diferentes: uma linha para cada."""
    app.dependency_overrides[get_news_fetcher] = _fetcher

    outra = client.post(
        '/key-accounts/',
        json={'nome': key_account.nome},
        headers=auth(other_kam_token),
    ).json()

    _buscar(client, kam_token, key_account)
    client.post(
        '/news/',
        json={'company': outra['nome'], 'key_account_id': outra['id']},
        headers=auth(other_kam_token),
    )

    assert _total(session) == DOIS_DONOS


def test_excluir_key_account_apaga_noticias(
    client, fake_news, kam_token, key_account, session
):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    _buscar(client, kam_token, key_account)
    assert _total(session) == 1

    response = client.delete(
        f'/key-accounts/{key_account.id}/', headers=auth(kam_token)
    )
    assert response.status_code == HTTPStatus.OK
    assert _total(session) == 0


# --------------------------------------------------------------------- #
# url_hash
# --------------------------------------------------------------------- #
def test_url_hash_usa_a_url():
    a = url_hash('m_a', 'texto um', 'https://exemplo.com')
    b = url_hash('expansao', 'texto dois', 'https://exemplo.com')
    assert a == b
    assert len(a) == URL_HASH_LEN


def test_url_hash_sem_url_cai_para_texto():
    a = url_hash('m_a', 'mesmo texto', None)
    b = url_hash('m_a', 'mesmo texto', '   ')
    c = url_hash('m_a', 'outro texto', None)
    assert a == b
    assert a != c


# --------------------------------------------------------------------- #
# Avaliação
# --------------------------------------------------------------------- #
def test_avaliar_like(client, fake_news, kam_token, key_account, session):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    noticia_id = _primeiro_id(_buscar(client, kam_token, key_account))

    response = client.put(
        f'/noticias/{noticia_id}/avaliacao/',
        json={'valor': 'like'},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['avaliacao'] == 'like'

    noticia = session.scalar(select(Noticia))
    session.refresh(noticia)
    assert noticia.avaliado_por_id is not None
    assert noticia.avaliado_em is not None


def test_trocar_avaliacao(client, fake_news, kam_token, key_account):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    noticia_id = _primeiro_id(_buscar(client, kam_token, key_account))
    url = f'/noticias/{noticia_id}/avaliacao/'

    client.put(url, json={'valor': 'like'}, headers=auth(kam_token))
    response = client.put(
        url, json={'valor': 'dislike'}, headers=auth(kam_token)
    )
    assert response.json()['avaliacao'] == 'dislike'


def test_desfazer_avaliacao(
    client, fake_news, kam_token, key_account, session
):
    """Clicar no botão ativo limpa: 'neutro' e 'não avaliada' são estados
    diferentes, e o dashboard precisa distinguir."""
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    noticia_id = _primeiro_id(_buscar(client, kam_token, key_account))
    url = f'/noticias/{noticia_id}/avaliacao/'

    client.put(url, json={'valor': 'neutro'}, headers=auth(kam_token))
    response = client.put(url, json={'valor': None}, headers=auth(kam_token))

    assert response.status_code == HTTPStatus.OK
    assert response.json()['avaliacao'] is None

    noticia = session.scalar(select(Noticia))
    session.refresh(noticia)
    assert noticia.avaliado_por_id is None
    assert noticia.avaliado_em is None


def test_avaliacao_invalida(client, fake_news, kam_token, key_account):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    noticia_id = _primeiro_id(_buscar(client, kam_token, key_account))

    response = client.put(
        f'/noticias/{noticia_id}/avaliacao/',
        json={'valor': 'otimo'},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_avaliar_noticia_inexistente(client, kam_token):
    response = client.put(
        '/noticias/9999/avaliacao/',
        json={'valor': 'like'},
        headers=auth(kam_token),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_avaliar_exige_token(client, fake_news, kam_token, key_account):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    noticia_id = _primeiro_id(_buscar(client, kam_token, key_account))

    response = client.put(
        f'/noticias/{noticia_id}/avaliacao/', json={'valor': 'like'}
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_kam_nao_avalia_noticia_de_outro(
    client, fake_news, kam_token, other_kam_token, key_account
):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    noticia_id = _primeiro_id(_buscar(client, kam_token, key_account))

    response = client.put(
        f'/noticias/{noticia_id}/avaliacao/',
        json={'valor': 'like'},
        headers=auth(other_kam_token),
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_admin_avalia_noticia_de_kam(
    client, fake_news, kam_token, admin_token, key_account
):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    noticia_id = _primeiro_id(_buscar(client, kam_token, key_account))

    response = client.put(
        f'/noticias/{noticia_id}/avaliacao/',
        json={'valor': 'like'},
        headers=auth(admin_token),
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['avaliacao'] == 'like'


# --------------------------------------------------------------------- #
# Histórico (GET /noticias/)
# --------------------------------------------------------------------- #
def _hist(client, token, query=''):
    return client.get(f'/noticias/{query}', headers=auth(token))


def test_historico_lista_o_que_foi_buscado(
    client, fake_news, kam_token, key_account
):
    """O motivo da aba: recarregar a tela não pode custar outra busca."""
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    _buscar(client, kam_token, key_account)

    response = _hist(client, kam_token)
    assert response.status_code == HTTPStatus.OK
    noticias = response.json()['noticias']
    assert len(noticias) == 1
    assert noticias[0]['empresa'] == key_account.nome
    assert noticias[0]['texto'] == 'Aquisição concluída.'
    assert noticias[0]['data'] == '2026-01-01'


def test_historico_exige_token(client):
    assert client.get('/noticias/').status_code == HTTPStatus.UNAUTHORIZED


def test_historico_vazio(client, kam_token):
    assert _hist(client, kam_token).json()['noticias'] == []


def test_historico_nao_mostra_noticia_de_outro(
    client, fake_news, kam_token, other_kam_token, key_account
):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    _buscar(client, kam_token, key_account)

    assert _hist(client, other_kam_token).json()['noticias'] == []
    assert len(_hist(client, kam_token).json()['noticias']) == 1


def test_historico_admin_ve_tudo(
    client, fake_news, kam_token, admin_token, key_account
):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    _buscar(client, kam_token, key_account)

    assert len(_hist(client, admin_token).json()['noticias']) == 1


def test_historico_filtra_por_empresa(
    client, fake_news, kam_token, key_account
):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    _buscar(client, kam_token, key_account)

    dentro = _hist(client, kam_token, f'?key_account_id={key_account.id}')
    assert len(dentro.json()['noticias']) == 1

    fora = _hist(client, kam_token, '?key_account_id=9999')
    assert fora.json()['noticias'] == []


def test_historico_filtra_por_carteira(
    client, fake_news, kam_token, carteira_com_ka, key_account
):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    _buscar(client, kam_token, key_account)

    dentro = _hist(client, kam_token, f'?carteira_id={carteira_com_ka.id}')
    assert len(dentro.json()['noticias']) == 1

    fora = _hist(client, kam_token, '?carteira_id=9999')
    assert fora.json()['noticias'] == []


def test_historico_filtra_por_avaliacao(
    client, fake_news, kam_token, key_account
):
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    noticia_id = _primeiro_id(_buscar(client, kam_token, key_account))

    # 'sem' pega as não avaliadas, que não são o mesmo que 'neutro'.
    assert len(_hist(client, kam_token, '?avaliacao=sem').json()['noticias'])
    assert _hist(client, kam_token, '?avaliacao=like').json()['noticias'] == []

    client.put(
        f'/noticias/{noticia_id}/avaliacao/',
        json={'valor': 'like'},
        headers=auth(kam_token),
    )

    assert len(_hist(client, kam_token, '?avaliacao=like').json()['noticias'])
    assert _hist(client, kam_token, '?avaliacao=sem').json()['noticias'] == []


def test_historico_filtro_avaliacao_invalido(client, kam_token):
    response = _hist(client, kam_token, '?avaliacao=otimo')
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_historico_filtra_por_periodo(
    client, fake_news, kam_token, key_account
):
    """A notícia do stub é de 2026-01-01, bem fora de 7 dias."""
    app.dependency_overrides[get_news_fetcher] = lambda: fake_news
    _buscar(client, kam_token, key_account)

    assert _hist(client, kam_token, '?dias=7').json()['noticias'] == []
    assert len(_hist(client, kam_token, '?dias=36500').json()['noticias']) == 1
