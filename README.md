# KAM News Digest

Briefings de notícias corporativas (resultados, M&A, expansão, liderança e
regulatório) para Key Account Managers. Backend **FastAPI** + frontend
**HTML/jQuery**, seguindo o mesmo padrão de projeto do `diytraining`
(layout `src/`, Poetry, taskipy, ruff, testes com `TestClient`, Docker).

As notícias vêm do **Google News RSS** (gratuito, sem chave) e o resumo é
feito por um **modelo local via Ollama** — **custo zero, sem chave de API**.

Carteiras, key accounts e usuários ficam em **PostgreSQL**, com autenticação
JWT: cada KAM enxerga a própria carteira e o administrador enxerga tudo. Cada
notícia é guardada com um botão de **boa / neutra / má**, formando o histórico
que alimentará o dashboard de "temperatura" da carteira.

## Estrutura

```
kam-news-digest/
├── pyproject.toml           # Poetry + ruff + pytest + taskipy
├── dockerfile
├── docker-compose.yaml
├── entrypoint.sh
├── .env.example             # = env.example.txt (cópias; manter iguais)
├── alembic.ini
├── migrations/              # versionamento do schema
├── CLAUDE.md
├── README.md
├── src/
│   └── kamnews/
│       ├── app.py           # FastAPI + include_router + monta o frontend
│       ├── settings.py      # pydantic-settings (banco, JWT, modelo, ...)
│       ├── database.py      # engine + get_session
│       ├── models.py        # SQLAlchemy: Role, User, Carteira, KeyAccount
│       ├── security.py      # hash de senha, JWT, get_current_user/admin
│       ├── noticias_service.py  # histórico de notícias + avaliação
│       ├── chat_context.py   # contexto do assistente (só da carteira)
│       ├── chat_tools.py     # RSS + leitura de página (guarda SSRF)
│       ├── chat_service.py   # LangChain + Groq
│       ├── schemas.py       # Schema / Public / List
│       ├── seed.py          # dados iniciais (idempotente)
│       ├── portfolios.py    # semente inicial das carteiras
│       ├── news_service.py  # Google News RSS + resumo via Ollama
│       ├── bootstrap.py     # espera o banco e o Ollama; baixa o modelo
│       ├── prompts/
│       │   └── company_news.txt   # template do prompt (string.Template)
│       ├── routers/
│       │   ├── auth.py       users.py       roles.py
│       │   ├── carteiras.py  key_accounts.py  noticias.py  chat.py
│       │   └── portfolios.py news.py
│       └── static/
│           └── index.html   # interface (CSS + jQuery)
└── tests/
    ├── conftest.py       # testcontainers: Postgres real
    ├── test_app.py       test_auth.py      test_users.py
    ├── test_carteiras.py test_key_accounts.py test_vinculos.py
    ├── test_portfolios.py test_seed.py     test_migration.py
    ├── test_noticias.py   # persistência, dedup e avaliação
    ├── test_chat.py       test_chat_tools.py
    ├── test_news.py      # rota /news/ com o fetcher sobrescrito
    ├── test_rss.py       # parse_rss / build_rss_url, sem I/O
    └── test_summary.py   # prompt, normalize_summary e _backfill
```

## Pré-requisitos

- **Docker** + **Docker Compose** (é só isso).

Não precisa instalar Python, Poetry, Ollama nem baixar modelo à mão, e não há
chave de API nem conta em serviço nenhum — tudo sobe em containers.

## Rodar (Docker — recomendado)

```bash
docker-compose up -d
```

Pronto. Abra <http://localhost:8000> (só acessível em localhost). Docs da API em
<http://localhost:8000/docs>.

O que acontece nos bastidores: sobem containers do **PostgreSQL**, do
**Ollama** e da aplicação; no start, o `entrypoint` espera o banco e o Ollama,
baixa o modelo automaticamente (`llama3.2`, ~2 GB), roda as migrations e semeia
os dados iniciais antes de servir.

### Primeiro acesso

A aplicação abre numa tela de login. O seed cria um administrador e um usuário
KAM por carteira:

| Usuário | E-mail | Senha | Papel |
|---|---|---|---|
| `master` | o seu `MASTER_EMAIL` | o seu `MASTER_PASSWORD` | Administrador |
| `Mayra`, `Adriana`, `Renata`, `Rogério` | `<nome>@<SEED_EMAIL_DOMAIN>` | o seu `SEED_KAM_PASSWORD` | KAM |

As senhas são as que **você** definiu no `.env` — não há senha padrão embutida.

> **Troque-as no primeiro acesso** (aba **Usuários**, como admin). O seed é
> idempotente e nunca reseta a senha de um usuário que já existe, então mudar
> o `.env` depois **não** muda a senha de quem já foi criado.

O admin vê todas as carteiras e a aba **Usuários**; cada KAM vê apenas as
próprias carteiras e key accounts.

> **Primeira execução demora** — o download do modelo pode levar alguns minutos.
> Acompanhe com `docker-compose logs -f kamnews_app` — o download aparece nos
> logs. Nas próximas vezes o modelo já está no volume e sobe rápido.

Comandos úteis:

```bash
docker-compose logs -f kamnews_app   # logs da app (inclui o download)
docker-compose ps                    # status dos serviços
docker-compose down                  # parar (mantém o modelo baixado)
```

Trocar o modelo (ex.: melhor qualidade em PT/JSON): edite `OLLAMA_MODEL` no
`docker-compose.yaml` (serviço `kamnews_app`) e rode `docker-compose up -d`
novamente.

> Compatível com `docker-compose` v1 (testado na 1.25.0) e com
> `docker compose` v2 — use o comando que você tiver.

## Rodar sem Docker (Poetry, opcional)

Requer Python 3.12+, Poetry, PostgreSQL e [Ollama](https://ollama.com).

```bash
ollama pull llama3.2        # baixa o modelo (uma vez)
ollama serve                # se ainda não estiver rodando
poetry install
task migrate                # cria o schema
task seed                   # dados iniciais (idempotente)
task run                    # http://localhost:8000
```

> O `.env` é opcional — os padrões apontam para um Postgres local em
> `localhost:5432` (base/usuário/senha `kamnews`).

## Testes

```bash
task test                   # lint + pytest + cobertura (HTML em htmlcov/)
```

Os testes não fazem chamadas reais à rede nem exigem o Ollama no ar: o
`fetch_company_news` é substituído por um stub via `app.dependency_overrides`,
e o parse do RSS e a normalização do resumo são funções puras.

> **Requer Docker rodando.** Os testes de rota sobem um PostgreSQL real via
> `testcontainers` (imagem `postgres:16`, baixada na primeira execução).

## Endpoints

Todas as rotas exigem `Authorization: Bearer <token>`, exceto `/`, `/health` e
`/auth/token`. Note a **barra final** — o frontend está montado em `/` e
engole requisições sem ela.

| Método | Rota | Acesso | Descrição |
|--------|------|--------|-----------|
| GET | `/` | público | Frontend (SPA). |
| GET | `/health` | público | Healthcheck (`{"message": "ok"}`). |
| POST | `/auth/token` | público | Login. Form-encoded: `username` (e-mail) + `password`. |
| POST | `/auth/refresh_token` | token | Renova o token. |
| GET | `/users/me/` | token | Usuário logado e seu papel. |
| GET/POST | `/users/` | admin | Lista / cria usuários. |
| PUT/DELETE | `/users/{id}/` | admin | Edita / remove. Senha em branco no PUT = não alterar. |
| GET | `/roles/` | admin | Papéis disponíveis. |
| GET/POST | `/carteiras/` | token | Lista (aceita `?status=`) / cria. |
| GET/PUT/DELETE | `/carteiras/{id}/` | token | Uma carteira. |
| POST/DELETE | `/carteiras/{id}/key-accounts/{ka_id}/` | token | Vincula / desvincula (idempotente). |
| GET/POST | `/key-accounts/` | token | Lista (aceita `?status=`) / cria. |
| GET/PUT/DELETE | `/key-accounts/{id}/` | token | Uma key account. |
| GET | `/portfolios/` | token | Carteiras ativas do usuário, com os clientes ativos. |
| GET | `/portfolios/{name}/` | token | Uma carteira. |
| POST | `/news/` | token | Busca notícias **e guarda no histórico**. Body: `{ "company", "date_str", "key_account_id", "data_inicio", "data_fim" }`. Período limitado aos últimos 60 dias (422 fora disso). |
| GET | `/noticias/` | token | Histórico salvo. Filtros: `carteira_id`, `key_account_id`, `avaliacao`, `dias`. |
| PUT | `/noticias/{id}/avaliacao/` | token | `{"valor": "like"\|"dislike"\|"neutro"\|null}`. `null` limpa a avaliação. |
| GET/POST | `/chat/conversas/` | token | Lista / cria conversa (exige `carteira_id`). |
| GET/DELETE | `/chat/conversas/{id}/` | token | Detalhe com mensagens / apaga. |
| POST | `/chat/conversas/{id}/mensagens/` | token | Pergunta ao assistente. |

O dono (`owner_id`) vem **sempre** do token, nunca do corpo. Um KAM que peça o
id de outro recebe **404**, não 403 — assim não vaza a existência de ids
alheios.

## Configuração (env / `.env`)

Nenhuma variável é obrigatória.

| Variável              | Padrão                | Descrição |
|-----------------------|-----------------------|-----------|
| `DATABASE_URL`        | `postgresql+psycopg://kamnews:kamnews@localhost:5432/kamnews` | Conexão com o Postgres. |
| `SECRET_KEY`          | `dev-only-trocar-em-producao` | Chave de assinatura do JWT. **Troque.** |
| `ALGORITHM`           | `HS256`               | Algoritmo do JWT. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480`         | Validade do token (8h). |
| `SEED_EMAIL_DOMAIN`   | `kamnews.com.br`      | Domínio dos e-mails do seed. Evite TLDs de uso especial (`.local`, `.internal`): o validador de e-mail os rejeita. |
| `MASTER_EMAIL`        | `admin@kamnews.com.br`| E-mail do admin inicial. |
| `MASTER_PASSWORD`     | `admin123`            | Senha do admin inicial. |
| `SEED_KAM_PASSWORD`   | `kamnews123`          | Senha inicial dos KAMs. |
| `OLLAMA_HOST`         | `http://localhost:11434` | Endereço do Ollama. |
| `OLLAMA_MODEL`        | `llama3.2`            | Modelo local para o resumo. |
| `OLLAMA_NUM_PREDICT`  | `700`                 | Limite de saída por empresa. |
| `OLLAMA_NUM_CTX`      | `4096`                | Janela de contexto do modelo. |
| `OLLAMA_TIMEOUT`      | `150`                 | Timeout (s) da chamada ao Ollama. |
| `NEWS_HL`             | `pt-BR`               | Idioma do Google News. |
| `NEWS_GL`             | `BR`                  | País do Google News. |
| `NEWS_CEID`           | `BR:pt-BR`            | País:idioma do Google News. |
| `NEWS_WINDOW_DAYS`    | `30`                  | Período padrão (dias) quando a busca não informa datas. Máx. 60. |
| `NEWS_MAX_ITEMS`      | `30`                  | Candidatos do RSS (já deduplicados) enviados ao modelo. |
| `NEWS_TARGET_ITEMS`   | `5`                   | Notícias no briefing final por empresa. |

## Cadastro de carteiras e key accounts

Pela aba **Cadastro**: criar, renomear, inativar/reativar e excluir carteiras e
key accounts, e vincular clientes à carteira clicando nos chips. O vínculo é
**N:N** — uma key account pode estar em várias carteiras do mesmo dono.

Inativar mantém o registro no cadastro mas o esconde do Digest; excluir apaga de
vez, junto com os vínculos (a key account em si sobrevive, e vice-versa).

O dicionário `PORTFOLIOS` em `src/kamnews/portfolios.py` agora é apenas a
**semente** usada pelo `seed.py` na primeira subida. Depois disso, a fonte da
verdade é o banco: editar o arquivo não muda nada em uma base já semeada.

O seed é idempotente e roda a cada boot — mas **não** desfaz um `inativo` posto
à mão, não desfaz um desvínculo e não reseta senha de usuário existente.

## Histórico de notícias e avaliação

Cada notícia do digest tem três botões no rodapé do item: **▲ boa**,
**● neutra** e **▼ má**. Clicar grava; clicar de novo no que já está ativo
limpa a avaliação.

A aba **Assistente** é um chat por carteira: ver *Assistente* abaixo.

A aba **Histórico** mostra tudo o que já foi buscado, em cards por empresa e
com os mesmos botões — assim recarregar a página não obriga a refazer a busca
(que leva ~2 min por empresa). Dá para filtrar por carteira, empresa, avaliação
e período.

As notícias ficam guardadas por key account. Rebuscar a mesma empresa **não
duplica**: a linha é reaproveitada pela URL, o texto é atualizado (o modelo
reescreve o resumo a cada execução) e **a avaliação é preservada**.

> A busca em si sempre refaz o caminho completo (Google News RSS + Ollama) —
> o banco guarda o histórico, não serve de cache.

Só empresas cadastradas como key account podem ser buscadas: é nelas que o
histórico se pendura. Uma empresa fora do cadastro devolve 404.

"Não avaliada" e "neutra" são estados **diferentes** — o dashboard futuro
precisa separar "olhei e achei sem impacto" de "ainda não olhei".

## Assistente

A aba **Assistente** é um chat preso a uma carteira. Ele recebe como contexto
os clientes daquela carteira, as notícias já salvas (com as avaliações) e a
temperatura por empresa — **e nada de outras carteiras**.

Quando a pergunta pede algo que não está no banco, ele busca sozinho:
notícias recentes no Google News (só de clientes da carteira) ou o conteúdo de
uma página citada. As fontes consultadas aparecem embaixo de cada resposta.

As conversas ficam salvas e voltam ao recarregar a página. As que ficam
**mais de 7 dias sem uso são apagadas** (`CHAT_HISTORY_DAYS`).

### Ligando o assistente

Diferente do resto do projeto, o chat usa um modelo na nuvem (Groq): um chat
precisa responder em segundos, e o Ollama local leva dezenas deles. É também a
única parte que manda dados para fora da sua máquina.

1. Pegue uma chave em <https://console.groq.com/> (aba *API Keys*).
2. Ponha em `GROQ_API_KEY`, no `.env` ou no `docker-compose.yaml`.

**Sem a chave a aba fica desligada**, respondendo 503 com um aviso — o resto da
aplicação segue funcionando normalmente.

## Segurança

- **Troque o `SECRET_KEY`** antes de expor a aplicação para fora do localhost:
  `openssl rand -hex 32`. Quem conhece o valor padrão consegue forjar tokens; a
  aplicação avisa nos logs enquanto o valor de desenvolvimento estiver em uso.
- **Os segredos ficam no `.env`**, que não é versionado. O
  `docker-compose.yaml` só referencia `${VAR}` — nenhum valor sensível entra
  no git. Copie de `.env.example` e preencha antes de subir.
- **Troque as senhas do seed** no primeiro acesso.
- A porta do app está publicada só em `127.0.0.1` e a do banco não está
  publicada — mantenha assim, a menos que saiba o que está fazendo.
- **O assistente manda o contexto da carteira para a Groq.** Se isso for
  inaceitável para os dados dos seus clientes, deixe `GROQ_API_KEY` vazia e a
  aba fica desligada.
- A leitura de páginas do assistente só alcança endereços públicos: a rede
  interna (banco, Ollama) e o metadata da nuvem ficam bloqueados.
