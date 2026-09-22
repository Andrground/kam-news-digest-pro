from http import HTTPStatus
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from kamnews.routers import (
    auth,
    carteiras,
    key_accounts,
    news,
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
app.include_router(news.router)

STATIC_DIR = Path(__file__).parent / 'static'


@app.get('/health', status_code=HTTPStatus.OK, response_model=Message)
def health():
    return {'message': 'ok'}


# Frontend (HTML + jQuery) servido na raiz.
app.mount('/', StaticFiles(directory=STATIC_DIR, html=True), name='static')
