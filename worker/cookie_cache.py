"""
Cookie Cache — salva cookies do Playwright por email no PostgreSQL.
Na próxima busca, carrega os cookies e vai direto pro Outlook (sem relogar).
Cookies ESTSAUTHPERSISTENT da MS podem durar até 90 dias.
"""

import os
import json
import time
import logging

logger = logging.getLogger("rpa")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://lkadmin:lkstore2026pg@postgres.railway.internal:5432/trocasdolk"
)

_db_conn = None
_use_db = True

# Cookies expiram após 7 dias no cache (mesmo que MS permita mais)
MAX_AGE_SECONDS = 7 * 24 * 3600


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
        logger.warning(f"[cookie_cache] DB indisponível, usando fallback JSON: {e}")
        _use_db = False
        return None


def _ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lklogins_cookie_cache (
                email TEXT PRIMARY KEY,
                cookies_json TEXT,
                updated_at BIGINT
            )
        """)


# === Fallback JSON ===
_JSON_PATH = os.path.join(os.path.dirname(__file__), "cookie_cache.json")


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
        logger.error(f"[cookie_cache] Falha ao salvar JSON: {e}")


# === API pública ===

def save_cookies(email: str, cookies: list):
    """Salva cookies do Playwright context após login bem-sucedido."""
    email = email.lower().strip()
    now = int(time.time())
    cookies_str = json.dumps(cookies)

    conn = _get_conn()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO lklogins_cookie_cache (email, cookies_json, updated_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (email) DO UPDATE SET
                        cookies_json = EXCLUDED.cookies_json,
                        updated_at = EXCLUDED.updated_at
                """, (email, cookies_str, now))
            logger.info(f"[cookie_cache] Cookies salvos no PostgreSQL para {email} ({len(cookies)} cookies)")
            return
        except Exception as e:
            logger.error(f"[cookie_cache] Erro ao salvar no DB: {e}")

    # Fallback JSON
    data = _load_json()
    data[email] = {"cookies_json": cookies_str, "updated_at": now}
    _save_json(data)
    logger.info(f"[cookie_cache] Cookies salvos em JSON para {email}")


def load_cookies(email: str) -> list | None:
    """Carrega cookies salvos. Retorna None se não existir ou expirado."""
    email = email.lower().strip()
    now = int(time.time())

    conn = _get_conn()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT cookies_json, updated_at FROM lklogins_cookie_cache WHERE email = %s",
                    (email,)
                )
                row = cur.fetchone()
                if row:
                    age = now - row[1]
                    if age > MAX_AGE_SECONDS:
                        logger.info(f"[cookie_cache] Cookies expirados para {email} (age={age//3600}h)")
                        delete_cookies(email)
                        return None
                    cookies = json.loads(row[0])
                    logger.info(f"[cookie_cache] Cookies carregados do DB para {email} ({len(cookies)} cookies, age={age//3600}h)")
                    return cookies
        except Exception as e:
            logger.error(f"[cookie_cache] Erro ao carregar do DB: {e}")

    # Fallback JSON
    data = _load_json()
    entry = data.get(email)
    if entry:
        age = now - entry.get("updated_at", 0)
        if age > MAX_AGE_SECONDS:
            logger.info(f"[cookie_cache] Cookies expirados (JSON) para {email}")
            del data[email]
            _save_json(data)
            return None
        cookies = json.loads(entry["cookies_json"])
        logger.info(f"[cookie_cache] Cookies carregados do JSON para {email} ({len(cookies)} cookies)")
        return cookies

    return None


def delete_cookies(email: str):
    """Remove cookies salvos (quando invalidados)."""
    email = email.lower().strip()

    conn = _get_conn()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM lklogins_cookie_cache WHERE email = %s", (email,))
            logger.info(f"[cookie_cache] Cookies removidos do DB para {email}")
        except Exception as e:
            logger.error(f"[cookie_cache] Erro ao deletar do DB: {e}")

    data = _load_json()
    if email in data:
        del data[email]
        _save_json(data)
