"""Guardas de configuração — o que impede a aplicação de subir torta."""

from kamnews.bootstrap import checar_secret_key
from kamnews.settings import DEV_SECRET_KEY, Settings


def _settings(secret):
    return Settings(SECRET_KEY=secret)


def test_secret_key_vazia_aborta(capsys):
    """O compose resolve ${SECRET_KEY} para '' quando falta o .env.

    Sem esta checagem a aplicação subiria assinando tokens com chave
    vazia, e nada no log denunciaria.
    """
    assert checar_secret_key(_settings('')) is False
    assert '.env' in capsys.readouterr().out


def test_secret_key_de_dev_apenas_avisa(capsys):
    assert checar_secret_key(_settings(DEV_SECRET_KEY)) is True
    assert 'ATENÇÃO' in capsys.readouterr().out


def test_secret_key_propria_passa_sem_ruido(capsys):
    assert checar_secret_key(_settings('a' * 64)) is True
    assert not capsys.readouterr().out
