from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from kamnews.routers import (
    auth,
    carteiras,
    chat,
    key_accounts,
    news,
    noticias,
    portfolios,
    roles,
    users,
)
from kamnews.schemas import Message

app = FastAPI(title='KAM News Digest')

# Todos os routers antes do mount da raiz: o StaticFiles em '/' engole
# qualquer rota registrada depois.
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(carteiras.router)
app.include_router(key_accounts.router)
app.include_router(portfolios.router)
app.include_router(noticias.router)
app.include_router(news.router)
app.include_router(chat.router)

STATIC_DIR = Path(__file__).parent / 'static'


@app.middleware('http')
async def no_cache_html(request: Request, call_next):
    """O SPA é um arquivo só, reescrito a cada deploy.

    O `StaticFiles` manda ETag e Last-Modified mas não `Cache-Control`;
    sem ele o navegador aplica cache heurístico e pode rodar JavaScript
    antigo contra uma API nova — o sintoma é a interface "não ter" algo
    que já está no servidor. `no-cache` obriga a revalidar; com o ETag,
    a revalidação custa um 304.
    """
    response = await call_next(request)
    content_type = response.headers.get('content-type', '')
    if content_type.startswith('text/html'):
        response.headers['Cache-Control'] = 'no-cache'
    return response


@app.get('/health', status_code=HTTPStatus.OK, response_model=Message)
def health():
    return {'message': 'ok'}


# Frontend (HTML + jQuery) servido na raiz.
app.mount('/', StaticFiles(directory=STATIC_DIR, html=True), name='static')
