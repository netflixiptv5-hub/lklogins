"""
Token Cache — salva access_token + refresh_token por email no PostgreSQL.
Na próxima busca, usa IMAP XOAUTH2 direto (sem relogar).
Fallback automático pro OAuth se token expirar.
"""

import os
import re
import base64
import imaplib
import logging
import json
import time
import urllib.parse
import httpx

logger = logging.getLogger("rpa")

# === Config OAuth (mesmo do api_login.py) ===
CLIENT_ID = "e9b154d0-7658-433b-bb25-6b8e0a8a7c59"
REDIRECT_URI = "msauth://com.microsoft.outlooklite/fcg80qvoM1YMKJZibjBwQcDfOno%3D"
SCOPE = "profile openid offline_access https://outlook.office.com/M365.Access"
IMAP_SERVER = "outlook.office365.com"
IMAP_PORT = 993

# === PostgreSQL ===
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://lkadmin:lkstore2026pg@postgres.railway.internal:5432/trocasdolk"
)

_db_conn = None
_use_db = True

def _get_conn():
    global _db_conn, _use_db
    if not _use_db:
        return None
    try:
        import psycopg2
        if _db_conn is None or _db_conn.closed:
            _db_conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
            _db_conn.autocommit = True
            _ensure_table(_db_conn)
        return _db_conn
    except Exception as e:
        logger.warning(f"[token_cache] DB indisponível, usando fallback JSON: {e}")
        _use_db = False
        return None

def _ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lklogins_token_cache (
                email TEXT PRIMARY KEY,
                access_token TEXT,
                refresh_token TEXT,
                cid TEXT,
                updated_at BIGINT
            )
        """)

# === Fallback: arquivo JSON local ===
_JSON_PATH = os.path.join(os.path.dirname(__file__), "token_cache.json")

def _load_json():
    try:
        with open(_JSON_PATH, "r") as f:
            return json.load(f)
    except:
        return {}

def _save_json(data):
    try:
        with open(_JSON_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"[token_cache] Falha ao salvar JSON: {e}")


# === API pública ===

def save_tokens(email: str, access_token: str, refresh_token: str, cid: str):
    """Salva tokens após login bem-sucedido."""
    email = email.lower().strip()
    now = int(time.time())

    conn = _get_conn()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO lklogins_token_cache (email, access_token, refresh_token, cid, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (email) DO UPDATE SET
                        access_token = EXCLUDED.access_token,
                        refresh_token = EXCLUDED.refresh_token,
                        cid = EXCLUDED.cid,
                        updated_at = EXCLUDED.updated_at
                """, (email, access_token, refresh_token, cid, now))
            logger.info(f"[token_cache] Tokens salvos no PostgreSQL para {email}")
            return
        except Exception as e:
            logger.error(f"[token_cache] Erro ao salvar no DB: {e}")

    # Fallback JSON
    data = _load_json()
    data[email] = {"access_token": access_token, "refresh_token": refresh_token, "cid": cid, "updated_at": now}
    _save_json(data)
    logger.info(f"[token_cache] Tokens salvos em JSON para {email}")


def load_tokens(email: str) -> dict | None:
    """Carrega tokens salvos. Retorna None se não existir."""
    email = email.lower().strip()

    conn = _get_conn()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT access_token, refresh_token, cid FROM lklogins_token_cache WHERE email = %s",
                    (email,)
                )
                row = cur.fetchone()
                if row:
                    return {"access_token": row[0], "refresh_token": row[1], "cid": row[2]}
        except Exception as e:
            logger.error(f"[token_cache] Erro ao carregar do DB: {e}")

    # Fallback JSON
    data = _load_json()
    return data.get(email)


def refresh_access_token(refresh_token: str, job_id: str = "") -> dict | None:
    """Usa o refresh_token pra obter novo access_token sem relogar."""
    try:
        token_data = (
            f"client_id={CLIENT_ID}"
            f"&grant_type=refresh_token"
            f"&refresh_token={urllib.parse.quote(refresh_token, safe='')}"
            f"&scope={urllib.parse.quote(SCOPE)}"
        )
        r = httpx.post(
            "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
            content=token_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "User-Agent": "Mozilla/5.0 (compatible; MSAL 1.0)",
            },
            timeout=15,
        )
        body = r.json()
        access_token = body.get("access_token")
        new_refresh = body.get("refresh_token", refresh_token)
        if access_token:
            logger.info(f"[{job_id}] Token renovado via refresh_token")
            return {"access_token": access_token, "refresh_token": new_refresh}
        else:
            logger.warning(f"[{job_id}] Refresh falhou: {str(body)[:100]}")
            return None
    except Exception as e:
        logger.error(f"[{job_id}] Erro no refresh: {e}")
        return None


def _build_xoauth2(email: str, access_token: str) -> str:
    """Monta string XOAUTH2 para IMAP."""
    auth_string = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
    return base64.b64encode(auth_string.encode()).decode()


def imap_login_with_token(email: str, access_token: str, job_id: str = "") -> imaplib.IMAP4_SSL | None:
    """Abre conexão IMAP usando access_token via XOAUTH2."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        xoauth2 = _build_xoauth2(email, access_token)
        mail.authenticate("XOAUTH2", lambda x: xoauth2)
        logger.info(f"[{job_id}] IMAP XOAUTH2 OK para {email}")
        return mail
    except Exception as e:
        logger.warning(f"[{job_id}] IMAP XOAUTH2 falhou: {e}")
        return None


def get_imap_connection(email: str, job_id: str = "") -> tuple[imaplib.IMAP4_SSL | None, dict | None]:
    """
    Tenta abrir IMAP usando tokens salvos.
    Retorna (conexão_imap, tokens_atualizados) ou (None, None) se falhar.
    Renova o token automaticamente se expirado.
    """
    tokens = load_tokens(email)
    if not tokens:
        logger.info(f"[{job_id}] Nenhum token salvo para {email}")
        return None, None

    # Tenta com access_token atual
    mail = imap_login_with_token(email, tokens["access_token"], job_id)
    if mail:
        return mail, tokens

    # Token expirado — tenta refresh
    logger.info(f"[{job_id}] Access token expirado, tentando refresh...")
    refreshed = refresh_access_token(tokens["refresh_token"], job_id)
    if refreshed:
        mail = imap_login_with_token(email, refreshed["access_token"], job_id)
        if mail:
            # Atualiza tokens salvos
            save_tokens(email, refreshed["access_token"], refreshed["refresh_token"], tokens.get("cid", ""))
            return mail, {**tokens, **refreshed}

    logger.info(f"[{job_id}] Cache falhou para {email}, vai usar OAuth normal")
    return None, None
