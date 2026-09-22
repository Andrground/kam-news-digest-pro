# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Guia para o Claude Code (e para humanos) trabalharem neste repositório. O
projeto segue **o mesmo padrão do `diytraining`**: FastAPI + layout `src/`,
Poetry, taskipy, ruff, testes com `TestClient`. Leia este arquivo antes de
alterar código e siga as convenções abaixo.

---

## 1. Visão geral

**KAM News Digest** gera briefings de notícias corporativas (resultados
financeiros, M&A, expansão, liderança, regulatório) para Key Account Managers.

- **Backend:** FastAPI. Busca as notícias no **Google News RSS** (gratuito,
  sem chave) e usa um **modelo local via Ollama** apenas para **classificar
  por tema e resumir**. Sem chave de API, custo zero.
- **Persistência:** PostgreSQL (SQLAlchemy 2.0 síncrono + Alembic) para
  carteiras, key accounts e usuários.
- **Autenticação:** JWT. Carteiras e key accounts têm **dono**: o KAM vê só o
  que é dele, o admin vê tudo.
- **Frontend:** `static/index.html` (HTML + jQuery), montado na raiz `/`.
  Tela de login + três abas: Digest, Cadastro e Usuários (só admin).
- **Idioma do produto:** português (mensagens, prompt e UI em pt-BR).

---

## 2. Stack

- Python **3.12+**
- **FastAPI** (`fastapi[standard]`) + **Pydantic v2**
- **pydantic-settings** para configuração
- **SQLAlchemy 2.0** (síncrono) + **Alembic** + **psycopg[binary]**
- **pyjwt** + **pwdlib[argon2]** — token e hash de senha
- **Ollama** (modelo local, ex.: `llama3.2`) — faz o resumo/classificação
- **httpx** — fala com o Google News RSS e com a API do Ollama
- **Poetry** (gerenciamento) + **taskipy** (tarefas)
- **ruff** (lint + format) / **pytest** + **pytest-cov** + **testcontainers**

---

## 3. Comandos

Tudo via [taskipy](https://github.com/taskipy/taskipy):

```bash
poetry install        # instala dependências

task run              # sobe o servidor FastAPI com auto-reload
task lint             # ruff check (sem auto-fix)
task format           # ruff check --fix + ruff format
task test             # lint + pytest com cobertura + relatório HTML
task migrate          # alembic upgrade head
task revision "msg"   # alembic revision --autogenerate
task seed             # dados iniciais (idempotente)

docker-compose up --build   # sobe via Docker (somente localhost)
```

Rodar um arquivo/teste específico:

```bash
pytest tests/test_news.py -s -x -vv
pytest tests/test_news.py::test_search_news -s -x -vv
```

> `pre_test` roda `task lint` antes dos testes: **o lint precisa passar**.

> **`task test` exige Docker rodando**: os testes de rota sobem um PostgreSQL
> real via `testcontainers` (`postgres:16`). `test_rss.py` e `test_summary.py`
> continuam sendo funções puras, sem container.

> `migrations/` está em `extend-exclude` do ruff: o código gerado pelo Alembic
> usa aspas duplas e passa de 79 colunas, e como `pre_test = 'task lint'` uma
> falha de lint abortaria o `task test` inteiro.

> `[tool.poetry] package-mode = false` — o `kamnews` **não** é instalado no
> ambiente. O pytest acha o pacote por `pythonpath = "src"` (em
> `pyproject.toml`); fora do pytest é preciso `PYTHONPATH=src` (é o que o
> `entrypoint.sh` faz no container).

---

## 4. Estrutura

```
kam-news-digest/
├── pyproject.toml           # Poetry + ruff + pytest + taskipy
├── dockerfile
├── docker-compose.yaml
├── entrypoint.sh
├── .env.example             # = env.example.txt (cópias; manter em sincronia)
├── .dockerignore / .gitignore
├── alembic.ini
├── migrations/              # env.py + versions/ (fora do lint)
├── CLAUDE.md                # este arquivo
├── README.md
├── src/
│   └── kamnews/
│       ├── __init__.py
│       ├── app.py           # FastAPI + include_router + monta o frontend
│       ├── settings.py      # pydantic-settings + get_settings() (lru_cache)
│       ├── database.py      # engine + get_session
│       ├── models.py        # Role, User, Carteira, KeyAccount + associação
│       ├── security.py      # hash, JWT, get_current_user/admin, ensure_owner
│       ├── schemas.py       # Pydantic: Schema / Public / List
│       ├── seed.py          # dados iniciais (idempotente)
│       ├── portfolios.py    # semente inicial (NÃO é lido em runtime)
│       ├── news_service.py  # Google News RSS + resumo via Ollama
│       ├── bootstrap.py     # espera banco e Ollama; baixa o modelo
│       ├── prompts/
│       │   └── company_news.txt   # template do prompt (string.Template)
│       ├── routers/
│       │   ├── auth.py / users.py / roles.py
│       │   ├── carteiras.py / key_accounts.py
│       │   └── portfolios.py / news.py
│       └── static/
│           └── index.html   # interface (CSS + jQuery embutidos)
└── tests/
    ├── __init__.py
    ├── conftest.py       # testcontainers + fixtures de papel/usuário/token
    ├── test_app.py / test_auth.py / test_users.py
    ├── test_carteiras.py / test_key_accounts.py / test_vinculos.py
    ├── test_portfolios.py / test_seed.py
    ├── test_migration.py # migration escrita à mão × models
    ├── test_news.py      # rota /news/ com o fetcher sobrescrito
    ├── test_rss.py       # parse_rss / build_rss_url, sem I/O
    └── test_summary.py   # build_user_prompt / normalize_summary /
                          # _backfill — o grosso da regra de negócio
```

**Onde mexer:**
- Nova rota/recurso → `routers/` + `schemas.py` (+ teste em `tests/`).
- Nova tabela/coluna → `models.py` + `task revision "msg"` (+ teste).
- Regra de negócio / chamada externa → módulo de serviço (`news_service.py`).
- Regra de permissão → `security.py` e o `scope()` do router.
- Configuração/env → `settings.py` + **os dois** arquivos `.env` de exemplo.

> `portfolios.py` **não é mais a fonte da verdade** — é só a semente do
> `seed.py`. Editar o dicionário não muda nada numa base já semeada.

---

## 5. Ciclo de uma requisição

1. **Autenticação** (`security.py`) resolve `get_current_user` pelo `sub`
   (e-mail) do JWT e rejeita usuário `inativo`.
2. **Router** (`routers/*.py`) recebe a requisição e aplica o `scope()` de
   propriedade (admin vê tudo; KAM filtra por `owner_id`).
3. **Schema** (`schemas.py`) valida entrada/saída (`response_model`).
4. **Serviço** (`news_service.py`) executa a lógica (busca RSS + Ollama).
5. **Banco** (`models.py` via `get_session`) fornece o domínio.
6. **Settings** (`settings.py`) leem `.env`/ambiente.

Frontend: a página abre na **tela de login**; sem token válido nada mais é
visível. Depois de autenticar, `loadPortfolios()` carrega as carteiras de
`GET /portfolios/` e cada empresa vai para `POST /news/` **uma de cada vez**
(`concurrency = 1` em `runSearch`: o Ollama atende um slot; paralelizar só
enfileira no servidor e estoura o timeout do jQuery, que é 240s). A exportação
Word (`.doc`) é gerada no navegador, sem backend.

Pontos do frontend que são carga de trabalho, não detalhe:
- O token fica em `localStorage`; `$.ajaxSetup` injeta o header em toda
  chamada e um `$(document).ajaxError` global trata 401 devolvendo ao login —
  **ignorando o `timeout` do `/news/`**, que dura minutos.
- `POST /auth/token` é **form-encoded** (`OAuth2PasswordRequestForm`), não
  JSON. Mandar JSON ali devolve 422 e parece erro de credencial.
- Escritas no Cadastro só marcam `cad.dirty`; o `loadPortfolios()` roda ao
  voltar para a aba Digest e **nunca** com `state.running` — recarregar no meio
  de uma busca corromperia `state.results`, que é indexado por nome de empresa.
- `loadPortfolios()` **reatribui** `PORTFOLIOS` (não muta), reconcilia
  `state.portfolio` e poda `state.selected`: sem isso, uma carteira renomeada
  deixa o digest vazio em silêncio.

---

## 6. Convenções de código (obrigatórias)

Ruff configurado em `pyproject.toml`:

- **Linha máx. 79 colunas.**
- **Aspas simples** (`quote-style = 'single'`).
- Regras: `select = ['I', 'F', 'E', 'W', 'PL', 'PT']` (import sort, pyflakes,
  pycodestyle, pylint, pytest).
- **Sem valores mágicos** (PLR2004): extraia números/sets para constantes de
  módulo (ex.: `MAX_ATTEMPTS`, `RETRYABLE_STATUS`).
- Status HTTP via `from http import HTTPStatus` (nunca números crus).
- Texto longo (prompts) **não** fica inline no código: use arquivo em
  `prompts/*.txt` carregado com `string.Template` (evita estourar 79 colunas e
  conflito com chaves `{}` de JSON — `Template` só interpreta `$`).

Sempre rode `task format` e garanta que `task lint` passe antes de commitar.

---

## 7. Receita — adicionar um novo recurso/rota

Exemplo: expor um recurso "watchlist".

1. **Schemas** em `schemas.py` (padrão Schema/Public/List):
   ```python
   class WatchlistSchema(BaseModel):
       name: str


   class WatchlistPublic(BaseModel):
       id: int
       name: str
       model_config = ConfigDict(from_attributes=True)


   class WatchlistList(BaseModel):
       watchlists: list[WatchlistPublic]
   ```
2. **Router** em `routers/watchlists.py`:
   ```python
   from http import HTTPStatus
   from fastapi import APIRouter, HTTPException
   from kamnews.schemas import WatchlistList, WatchlistPublic

   router = APIRouter(prefix='/watchlists', tags=['watchlists'])


   @router.get('/', response_model=WatchlistList)
   def read_watchlists(): ...
   ```
3. **Registrar** em `app.py`:
   ```python
   from kamnews.routers import watchlists

   app.include_router(watchlists.router)
   ```
   > `app.include_router(...)` deve vir **antes** do `app.mount('/', StaticFiles(...))`,
   > senão o mount na raiz captura a rota.
4. **Teste** em `tests/test_watchlists.py` usando a fixture `client`.

Padrões dos handlers (siga `routers/portfolios.py` e `routers/news.py`):
- `APIRouter(prefix='/x', tags=['x'])`.
- Dependências como aliases `Annotated`: `T_Session = Annotated[...]`.
- Erros: `raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail='...')`.
- Sempre declarar `response_model`.

---

## 8. Padrão de serviço + injeção de dependência

Regra de negócio e chamadas externas ficam em módulos de serviço, expostos ao
router por uma dependência simples — assim os testes trocam por um stub.

```python
# routers/news.py
def get_news_fetcher() -> NewsFetcher:
    return fetch_company_news


T_Fetcher = Annotated[NewsFetcher, Depends(get_news_fetcher)]


@router.post('/', response_model=CompanyNews)
async def search_news(request: NewsRequest, fetch: T_Fetcher): ...
```

Nos testes:

```python
app.dependency_overrides[get_news_fetcher] = lambda: fake_news
```

(É o equivalente ao override de `get_session` no `diytraining`.)

Para banco e autenticação o padrão é o mesmo, com aliases no topo do router:

```python
T_Session = Annotated[Session, Depends(get_session)]   # database.py
T_CurrentUser = Annotated[User, Depends(get_current_user)]   # security.py
T_CurrentAdmin = Annotated[User, Depends(get_current_admin)]
```

Nos testes, `app.dependency_overrides[get_session] = lambda: session`.

As `Settings` são resolvidas **lazy** por `get_settings()` (`@lru_cache`, em
`settings.py`) e `create_engine()` não abre conexão. Por isso importar o app
**não** exige banco, rede nem Ollama no ar — é o que mantém `/health`, `/` e os
testes de RSS/summary offline.

**Propriedade** (`owner_id`): o dono vem **sempre** do token, nunca do corpo —
aceitar `owner_id` do cliente deixaria qualquer KAM criar no nome de outro. Os
routers aplicam `scope(stmt, user)`, e um id fora do escopo devolve **404**
(não 403), para não vazar a existência de ids alheios.

---

## 9. Testes

- Usam `fastapi.testclient.TestClient`.
- Um arquivo por recurso (`test_<recurso>.py`), asserts com `HTTPStatus`.
- Fixtures em `tests/conftest.py`:
  - `engine` — `PostgresContainer('postgres:16', driver='psycopg')`, escopo de
    sessão (**exige Docker**).
  - `session` — `create_all` / `drop_all` por teste.
  - `client` — sobrescreve `get_session` e limpa `dependency_overrides`.
  - `role_admin` / `role_kam` — **get-or-create**, para compor com `seeded`.
  - `admin_user`, `kam_user`, `other_kam_user` + os `*_token` correspondentes.
  - `carteira`, `key_account`, `carteira_com_ka`, `seeded`.
  - `fake_news` — stub async no lugar de `fetch_company_news`.
  - `auth(token)` — monta o header `Authorization`.
- **Nenhuma chamada real à API externa** nos testes (o Postgres é local, em
  container).
- O admin de teste é `admin-teste`, **não** `master`: o `seed` já usa `master`
  e os dois precisam coexistir no mesmo teste.
- `test_migration.py` roda `alembic upgrade head` e compara com o metadata —
  é o que impede a migration escrita à mão de divergir dos models.

Cobertura sai em `htmlcov/` após `task test`.

---

## 10. Configuração / variáveis de ambiente

`settings.py` (`Settings(BaseSettings)`, lê `.env`):

| Variável              | Padrão                | Obrig. |
|-----------------------|-----------------------|:------:|
| `DATABASE_URL`        | `postgresql+psycopg://kamnews:kamnews@localhost:5432/kamnews` | não |
| `SECRET_KEY`          | `dev-only-trocar-em-producao` | não |
| `ALGORITHM`           | `HS256`               |  não   |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480`         |  não   |
| `SEED_EMAIL_DOMAIN`   | `kamnews.com.br`      |  não   |
| `MASTER_EMAIL`        | `admin@kamnews.com.br`|  não   |
| `MASTER_PASSWORD`     | `admin123`            |  não   |
| `SEED_KAM_PASSWORD`   | `kamnews123`          |  não   |
| `OLLAMA_HOST`         | `http://localhost:11434` | não |
| `OLLAMA_MODEL`        | `llama3.2`            |  não   |
| `OLLAMA_NUM_PREDICT`  | `700`                 |  não   |
| `OLLAMA_NUM_CTX`      | `4096`                |  não   |
| `OLLAMA_TIMEOUT`      | `150`                 |  não   |
| `NEWS_HL`             | `pt-BR`               |  não   |
| `NEWS_GL`             | `BR`                  |  não   |
| `NEWS_CEID`           | `BR:pt-BR`            |  não   |
| `NEWS_WINDOW_DAYS`    | `30`                  |  não   |
| `NEWS_MAX_ITEMS`      | `30`                  |  não   |
| `NEWS_TARGET_ITEMS`   | `5`                   |  não   |

**Nenhuma variável é obrigatória** — os padrões funcionam com um Postgres e um
Ollama locais. O `.env` é opcional.

Duas armadilhas já pagas:
- **`SECRET_KEY` tem default de desenvolvimento** para manter a regra acima.
  Quem conhece o valor forja tokens; o `bootstrap.py` avisa em destaque
  enquanto ele estiver em uso. Antes de expor fora do localhost:
  `openssl rand -hex 32`.
- **`SEED_EMAIL_DOMAIN` não pode ser um TLD de uso especial.** `.local` e
  `.internal` passam no banco mas o `EmailStr` do `UserPublic` os rejeita, e
  `/users/me/` devolve 500. `test_seeded_emails_are_serializable` guarda isso.

---

## 11. Fonte de notícias e modelo (custo zero)

> Esta seção descreve o pipeline de notícias, que **não** mudou com o banco.

- **Busca:** `fetch_rss_items` monta a URL do **Google News RSS**
  (`build_rss_url`) por empresa e baixa via `httpx`; `parse_rss` extrai
  título, fonte, data e URL (stdlib `xml.etree`).
- **Resumo:** `_call_ollama` envia os itens ao **Ollama** (`/api/chat`,
  `format: json`, `stream: false`), que classifica por tema e escreve os
  bullets. Roda 100% local — **sem chave e sem custo de API**.
- **Modelo:** padrão `llama3.2`. Requer Ollama instalado e o modelo baixado
  (`ollama pull llama3.2`). Trocável por env (`OLLAMA_MODEL`), ex.:
  `qwen2.5` costuma ir bem em português + JSON.
- **Erros amigáveis:** se o Ollama não estiver rodando (`ConnectError`) ou o
  modelo não existir (404), a mensagem orienta o que fazer.
- **Retry seletivo:** `MAX_ATTEMPTS = 3` com backoff no RSS e em erros HTTP
  genéricos do Ollama. `_call_ollama` **não** repete em `TimeoutException`
  (cada tentativa custaria `OLLAMA_TIMEOUT` inteiro), `ConnectError` nem 404 —
  falha rápido com mensagem acionável. O parse do JSON é tolerante
  (`extract_json`). O `response_model` `CompanyNews` usa aliases
  (`temNoticias`, `manchetePrincipal`) — saída em camelCase (o frontend
  depende disso).
- **Regra anti-alucinação + itens por `id`:** o prompt manda usar SOMENTE os
  itens do RSS e devolver apenas `{"id": N, "texto": "..."}`. `build_user_prompt`
  envia só `id`/`titulo`/`fonte`; `_origin` reanexa fonte, data e URL originais
  pelo índice. As URLs do Google News têm 200+ chars em base64 — mandá-las ao
  modelo estoura o `num_ctx` e multiplica o tempo de geração.
- **Volume do briefing:** o funil é `NEWS_MAX_ITEMS` candidatos (RSS já
  deduplicado por título, na ordem de relevância do Google) → o modelo
  classifica e resume → `normalize_summary` roda o pipeline nesta ordem:
  `_categoria`/`_clean_items` (coerção ao schema) → `_merge_temas` (junta
  categoria repetida) → `_trim_total` (round-robin até `NEWS_TARGET_ITEMS`)
  → `_backfill`. O teto por tema é `MAX_ITEMS_PER_THEME = 4`, constante de
  módulo em `news_service.py` (fica abaixo do alvo de propósito).
- **Complemento (`_backfill`):** o modelo costuma devolver menos que o
  alvo. Quando isso acontece, os candidatos que ele não escolheu entram
  na fila — em ordem de relevância — classificados por palavra-chave
  (`FALLBACK_KEYWORDS`), com o próprio título do RSS como `texto`.
  Ruído de mercado (`NOISE_KEYWORDS`: pregão, cotação etc.) e títulos que
  não casam com nenhum tema ficam de fora, então o briefing pode terminar
  abaixo do alvo — é melhor que encher com lixo. Nada é inventado aqui:
  o texto é a manchete real, sem o sufixo ` - Veículo`.
- **Categorias tolerantes:** `_categoria` normaliza o que o modelo
  escreveu (`CATEGORY_ALIASES`) em vez de descartar o tema inteiro; antes,
  um `"resultados"` no lugar de `"resultados_financeiros"` sumia calado.

## 12. Docker (self-contained)

O `docker-compose.yaml` sobe **tudo**: Postgres + Ollama + app. Escrito para
funcionar em **Compose v1 (1.25+) e v2** — por isso **sem** `${VAR:-default}`
e **sem** `condition: service_completed_successfully` (v1 não suporta).

- `kamnews_database` — Postgres 16 (volume `pgdata`). **Sem `ports:`**: o app
  fala pela rede interna. Mesma tag do testcontainer, de propósito.
- `ollama` — servidor do modelo (volume `ollama_data` persiste os modelos).
- `kamnews_app` — a API, em `127.0.0.1:8000`. O `entrypoint.sh` roda
  `python -m kamnews.bootstrap` (espera o **banco** primeiro — é rápido, e
  falhar aí é melhor que falhar depois de um pull de vários minutos — depois o
  Ollama e o modelo), então `alembic upgrade head`, `python -m kamnews.seed` e
  por fim `fastapi run`.

`set -e` no `entrypoint.sh` é intencional: sem ele, uma migration falha deixaria
a app subir contra um banco sem schema, devolvendo 500 em todas as rotas.

`depends_on` sem `condition:` só ordena o start, não espera readiness — por isso
a espera fica no `bootstrap.py`, em Python, e não num laço de shell.

```bash
docker-compose up -d                 # http://localhost:8000
docker-compose logs -f kamnews_app   # acompanha o download do modelo
```

Trocar modelo: edite `OLLAMA_MODEL` no `docker-compose.yaml`.

---

## 13. Endpoints

Só `/`, `/health` e `/auth/token` são públicas; o resto exige
`Authorization: Bearer`.

| Método | Rota | Acesso | Descrição |
|--------|------|--------|-----------|
| GET | `/` | público | Frontend (SPA). |
| GET | `/health` | público | `{"message": "ok"}`. |
| POST | `/auth/token` | público | Login **form-encoded**. 400 genérico (inclusive para usuário inativo). |
| POST | `/auth/refresh_token` | token | Renova. |
| GET | `/users/me/` | token | Usuário logado + papel. |
| GET/POST | `/users/` | admin | Lista / cria. 400 duplicado, 404 `Role not found`. |
| PUT/DELETE | `/users/{id}/` | admin | `password` ausente no PUT = não altera. DELETE: 400 se for o próprio, 409 se tiver carteiras. |
| GET | `/roles/` | admin | Popula o `<select>` do formulário. |
| GET/POST | `/carteiras/` | token | `?status=`, `limit`, `skip`. |
| GET/PUT/DELETE | `/carteiras/{id}/` | token | 404 fora do escopo. |
| POST/DELETE | `/carteiras/{id}/key-accounts/{ka_id}/` | token | Vincula/desvincula, **idempotente**, devolve a `CarteiraPublic`. |
| GET/POST | `/key-accounts/` | token | Idem carteiras. |
| GET/PUT/DELETE | `/key-accounts/{id}/` | token | Idem. |
| GET | `/portfolios/` | token | Carteiras `ativo` do usuário, clientes `ativo`. Ordem **alfabética**. |
| GET | `/portfolios/{name}/` | token | Uma carteira (404). |
| POST | `/news/` | token | Busca notícias. Body `{ "company": "...", "date_str": "..." }`. |

> A shape de `/portfolios/` é idêntica à do dicionário antigo — o digest
> depende dela. A ordem, porém, virou alfabética: a carteira default do admin
> mudou de Mayra para Adriana. É esperado, não é bug.

Docs automáticas: `/docs` (Swagger) e `/redoc`.

---

## 14. Checklist antes de commitar

- [ ] `task format` aplicado.
- [ ] `task lint` sem erros.
- [ ] `task test` verde (todos passando).
- [ ] Rota nova registrada em `app.py` **antes** do mount da raiz.
- [ ] Rota com **barra final** (o mount em `/` engole quem não tem).
- [ ] `response_model` declarado; erros com `HTTPException` + `HTTPStatus`.
- [ ] Rota nova exige token; se lista recurso com dono, aplica `scope()`.
- [ ] Mudou model? Gerou migration (`task revision`) e `test_migration.py` passa.
- [ ] Mudou env? Atualizou **os dois** `.env` de exemplo
      (`diff .env.example env.example.txt` vazio) e a tabela da §10.
- [ ] Sem segredos no código; `.env` fora do versionamento.
