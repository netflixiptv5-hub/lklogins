"""
Job Logger — salva logs por job no PostgreSQL.
Endpoint /api/logs/:jobId pra consultar.
"""

import os
import json
import time
import logging
import threading

logger = logging.getLogger("rpa")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://lkadmin:lkstore2026pg@postgres.railway.internal:5432/trocasdolk"
)

_db_conn = None
_use_db = True
_lock = threading.Lock()

# Buffer em memória pra quando DB não tá disponível
_memory_logs = {}  # job_id -> [entries]
MAX_MEMORY_ENTRIES = 200  # máximo de entradas por job na memória


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
        _use_db = False
        return None


def _ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS lklogins_job_logs (
                id SERIAL PRIMARY KEY,
                job_id TEXT NOT NULL,
                ts BIGINT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_logs_job_id ON lklogins_job_logs(job_id)
        """)


def log(job_id: str, message: str, level: str = "info"):
    """Salva uma entrada de log pro job."""
    now = int(time.time() * 1000)  # ms

    # Salva no DB
    conn = _get_conn()
    if conn:
        try:
            with _lock:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO lklogins_job_logs (job_id, ts, level, message) VALUES (%s, %s, %s, %s)",
                        (job_id, now, level, message[:2000])
                    )
            return
        except Exception as e:
            pass

    # Fallback: memória
    with _lock:
        if job_id not in _memory_logs:
            _memory_logs[job_id] = []
        if len(_memory_logs[job_id]) < MAX_MEMORY_ENTRIES:
            _memory_logs[job_id].append({"ts": now, "level": level, "message": message[:2000]})


def get_logs(job_id: str) -> list:
    """Retorna logs de um job."""
    conn = _get_conn()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ts, level, message FROM lklogins_job_logs WHERE job_id = %s ORDER BY ts ASC LIMIT 500",
                    (job_id,)
                )
                rows = cur.fetchall()
                return [{"ts": r[0], "level": r[1], "message": r[2]} for r in rows]
        except:
            pass

    # Fallback: memória
    return _memory_logs.get(job_id, [])


def cleanup_old_logs(max_age_hours: int = 24):
    """Remove logs antigos."""
    conn = _get_conn()
    if conn:
        try:
            cutoff = int((time.time() - max_age_hours * 3600) * 1000)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM lklogins_job_logs WHERE ts < %s", (cutoff,))
        except:
            pass

    # Limpa memória também
    with _lock:
        cutoff = int((time.time() - max_age_hours * 3600) * 1000)
        for jid in list(_memory_logs.keys()):
            _memory_logs[jid] = [e for e in _memory_logs[jid] if e["ts"] > cutoff]
            if not _memory_logs[jid]:
                del _memory_logs[jid]


class JobLogHandler(logging.Handler):
    """
    Handler que intercepta logs do logger 'rpa' e salva por job_id.
    Detecta o [job_id] no início da mensagem.
    """
    def emit(self, record):
        try:
            msg = self.format(record)
            # Extrai job_id do formato "[job_id] mensagem"
            if msg.startswith("["):
                end = msg.find("]")
                if end > 0:
                    job_id = msg[1:end].strip()
                    message = msg[end+1:].strip()
                    level = record.levelname.lower()
                    log(job_id, message, level)
        except:
            pass
