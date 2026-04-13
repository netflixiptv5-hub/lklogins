"""
Netflix Email Link Extractor - RPA Worker (FAST version)
Optimized for speed: minimal sleeps, smart waits, direct navigation.
"""

import json
import time
import re
import logging
import os
import imaplib
import email as email_lib
from email.header import decode_header
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
import urllib.request
import traceback
import threading
import random
from email.utils import parsedate_to_datetime
from cookie_cache import save_cookies, load_cookies, delete_cookies

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("RPA")

# Registra handler pra salvar logs por job
try:
    from job_logger import JobLogHandler, cleanup_old_logs
    _job_handler = JobLogHandler()
    _job_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_job_handler)
except Exception as _e:
    print(f"[WARNING] job_logger não disponível: {_e}")

# === CONFIG ===
# Jobs aguardando clique do cliente no CAPTCHA interativo
# { job_id: { "page": page_obj, "event": threading.Event(), "click": (x,y) or None } }
_captcha_waiting = {}
_captcha_lock = threading.Lock()

HOTMAIL_PASSWORD = "02022013L"
HOTMAIL_PASSWORD_ALT = "A29b92c10@"
# === Gmail accounts (login directly, not via MS) ===
GMAIL_ACCOUNTS = {
    "ck100k2@gmail.com": "02022013L",
}

# === Gmail IMAP direct (senha de app) ===
GMAIL_IMAP_ACCOUNTS = {
    "ck100k2@gmail.com": "hfxcbsmvviiojkiw",
    "tech34011@gmail.com": "uwoyllawskfdeyja",
}

RECOVERY_DOMAIN = "cinepremiu.com"
RECOVERY_IMAP_SERVER = "webmail.amen.pt"
RECOVERY_EMAIL = "catchall@cinepremiu.com"
RECOVERY_PASSWORD = "02022013L@@@@"

# Known recovery emails used for MS identity verification
# When MS shows masked email like "te*****@gm...", we match against these
KNOWN_RECOVERY_EMAILS = [
    "tech34011@gmail.com",
    "tech.34011@gmail.com",
    "tech34.011@gmail.com",
    "t.ech34011@gmail.com",
    "te.ch34011@gmail.com",
    "tec.h34011@gmail.com",
    "tech3.4011@gmail.com",
    "tech340.11@gmail.com",
    "tech3401.1@gmail.com",
    "te.ch3.4011@gmail.com",
    "catchall@cinepremiu.com",
]
_server_port = os.environ.get("PORT", "3000")
API_BASE = os.environ.get("API_BASE", f"http://localhost:{_server_port}")
MAX_WORKERS = 3
SEARCH_MINUTES = 15

# === Netflix email subject patterns ===
EMAIL_PATTERNS = {
    "password_reset": [
        "complete a solicitação de redefinição de senha",
        "redefinição de senha", "redefina sua senha", "redefinir senha",
        "solicitação de redefinição",
        "complete your password reset", "password reset request",
        "reset your password", "password reset",
        "completa tu solicitud de restablecimiento",
        "restablecimiento de contraseña", "restablecer tu contraseña",
        "réinitialisation de mot de passe",
        "passwort zurücksetzen", "reimpostazione della password",
    ],
    "household_update": [
        "como atualizar sua residência", "atualizar residência netflix",
        "atualize sua residência", "atualização de residência",
        "how to update your netflix household", "update your netflix household",
        "netflix household", "update your household",
        "cómo actualizar tu hogar netflix", "actualizar tu hogar",
        "mettre à jour votre foyer", "netflix-haushalt aktualisieren",
    ],
    "temp_code": [
        "código de acesso", "seu código de acesso",
        "código de acesso temporário", "seu código de acesso temporário",
        "código temporário",
        "temporary access code", "your temporary access code",
        "código de acceso temporal", "tu código de acceso temporal",
        "code d'accès temporaire", "temporärer zugangscode",
    ],
    "netflix_disconnect": [
        "confirme a alteração da sua conta com este código",
        "confirme a alteração", "alteração da sua conta",
        "confirm your account change", "confirm the change to your account",
        "confirma el cambio de tu cuenta",
    ],
    "prime_code": [
        "verification code", "código de verificação", "otp",
        "código de verificación", "código de segurança",
        "one-time", "one time", "acesso", "verificação",
    ],
    "disney_code": [
        "verification code", "código de verificação", "otp",
        "one-time", "one time", "código de uso único",
        "reset", "redefin", "código de acesso",
    ],
    "globo_reset": [
        "redefinição de senha", "redefinir senha", "redefinir sua senha",
        "redefina sua senha", "password reset", "reset your password",
        "nova senha", "alteração de senha",
        "recuperar sua senha", "clique para recuperar", "recuperar senha",
    ],
}

# === Sender patterns for IMAP direct search ===
IMAP_SENDER_PATTERNS = {
    "netflix_disconnect": ["netflix", "info@account.netflix.com"],
    "prime_code": ["amazon", "prime", "primevideo"],
    "disney_code": ["disney", "disneyplus"],
    "globo_reset": ["globo", "globoplay"],
    "password_reset": ["netflix", "info@account.netflix.com"],
    "household_update": ["netflix", "info@account.netflix.com"],
    "temp_code": ["netflix", "info@account.netflix.com"],
}

# === Emails that go directly to cinepremiu IMAP (no MS login needed) ===
IMAP_DIRECT_EMAILS = [
    # Pattern: if email matches any of these, use IMAP direct
    r".*@cinepremiu\.com$",
    r"^netflixiptv\+.*@gmail\.com$",
    r"^ox21112s\+.*@gmail\.com$",
    r"^tech34011(\+.*)?@gmail\.com$",
]


def _should_use_headless() -> bool:
    """Check if we should use headless mode (Xvfb not available)."""
    if os.environ.get("XVFB_FAILED") == "1":
        return True
    import subprocess
    try:
        subprocess.run(["xdpyinfo"], capture_output=True, timeout=3, check=True)
        return False
    except:
        return True


def update_job(job_id: str, status: str, link=None, code=None, message=None, method=None, eta=None, expired=None):
    try:
        data = json.dumps({
            "jobId": job_id, "status": status,
            "link": link, "code": code, "message": message,
            "method": method, "eta": eta, "expired": expired,
        }).encode()
        req = urllib.request.Request(
            f"{API_BASE}/api/update", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.error(f"[{job_id}] Update failed: {e}")


def _is_email_expired(msg_or_date_str, max_age_minutes: int = 15) -> bool:
    """Check if an email is older than max_age_minutes.
    Accepts email.message.Message or date string."""
    try:
        if hasattr(msg_or_date_str, 'get'):
            date_str = msg_or_date_str.get("Date", "")
        else:
            date_str = str(msg_or_date_str)
        if not date_str:
            return False  # Can't determine, assume not expired
        dt = parsedate_to_datetime(date_str)
        from datetime import timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age = (now - dt).total_seconds() / 60
        return age > max_age_minutes
    except:
        return False  # Can't parse, assume not expired


def resolve_all_recovery_emails(masked_prefix: str, masked_domain_hint: str, job_id: str) -> list:
    """Find ALL candidate recovery emails from masked hint shown by MS.
    Returns a list of all matches sorted by length (shortest first).
    """
    prefix_lower = masked_prefix.lower().replace(".", "")
    domain_hint = masked_domain_hint.lower().rstrip(".")
    
    candidates = []
    for known in KNOWN_RECOVERY_EMAILS:
        local, domain = known.lower().split("@")
        local_nodots = local.replace(".", "")
        if not local_nodots.startswith(prefix_lower):
            continue
        if domain.startswith(domain_hint) or domain_hint.startswith(domain.split(".")[0]):
            candidates.append(known)
    
    if candidates:
        candidates = sorted(candidates, key=len)
        logger.info(f"[{job_id}] All candidates for {masked_prefix}***@{masked_domain_hint}: {candidates}")
    
    return candidates


def resolve_recovery_email(masked_prefix: str, masked_domain_hint: str, job_id: str) -> str | None:
    """Find the real recovery email from masked hint shown by MS.
    
    MS shows something like 'te*****@gm' or 'ca***@cinepremiu.com'.
    We first check KNOWN_RECOVERY_EMAILS, then fallback to IMAP search.
    
    masked_prefix: e.g. 'te', 'ca', 'tech3'
    masked_domain_hint: e.g. 'gm', 'gmail.com', 'cinepremiu.com' (may be truncated)
    """
    prefix_lower = masked_prefix.lower().replace(".", "")
    domain_hint = masked_domain_hint.lower().rstrip(".")
    
    # Step 1: Match against known recovery emails
    candidates = resolve_all_recovery_emails(masked_prefix, masked_domain_hint, job_id)
    
    if candidates:
        result = candidates[0]
        logger.info(f"[{job_id}] Resolved from known list: {masked_prefix}***@{masked_domain_hint} -> {result} ({len(candidates)} total candidates)")
        return result
    
    # Step 2: Fallback — search IMAP for recent MS emails
    try:
        mail = imaplib.IMAP4_SSL(RECOVERY_IMAP_SERVER, 993, timeout=10)
        mail.login(RECOVERY_EMAIL, RECOVERY_PASSWORD)
        mail.select("INBOX", readonly=True)
        cutoff = (datetime.now() - timedelta(minutes=60*24*7)).strftime("%d-%b-%Y")
        
        status, msg_ids = mail.search(None, f'(FROM "microsoft" SINCE "{cutoff}")')
        
        if status == "OK" and msg_ids[0]:
            found_emails = set()
            for msg_id in reversed(msg_ids[0].split()[-50:]):
                try:
                    _, data = mail.fetch(msg_id, "(BODY[HEADER.FIELDS (TO)])")
                    to_header = data[0][1].decode("utf-8", errors="replace").strip()
                    to_match = re.search(r'[\w.+-]+@[\w.-]+\.com', to_header, re.IGNORECASE)
                    if to_match:
                        to_email = to_match.group(0).lower()
                        local_part = to_email.split("@")[0].replace(".", "")
                        if local_part.startswith(prefix_lower):
                            found_emails.add(to_email)
                except:
                    continue
            
            mail.logout()
            
            if found_emails:
                real_email = sorted(found_emails, key=len)[0]
                logger.info(f"[{job_id}] Resolved via IMAP: {masked_prefix}*** -> {real_email}")
                return real_email
            else:
                logger.warning(f"[{job_id}] No IMAP match for prefix '{masked_prefix}' domain hint '{masked_domain_hint}'")
        else:
            mail.logout()
    except Exception as e:
        logger.error(f"[{job_id}] resolve_recovery_email error: {e}")
    
    return None
    
    return None


def get_ms_verification_code(target_email: str, job_id: str, max_wait: int = 60, min_timestamp: float = 0) -> str | None:
    """Get Microsoft verification code from @cinepremiu.com via IMAP.
    min_timestamp: only accept emails received AFTER this unix timestamp (to skip old codes).
    """
    logger.info(f"[{job_id}] Waiting for MS verification code...")
    start = time.time()
    seen_ids = set()

    while time.time() - start < max_wait:
        try:
            mail = imaplib.IMAP4_SSL(RECOVERY_IMAP_SERVER, 993, timeout=10)
            mail.login(RECOVERY_EMAIL, RECOVERY_PASSWORD)
            mail.select("INBOX", readonly=True)
            cutoff = (datetime.now() - timedelta(minutes=5)).strftime("%d-%b-%Y")
            
            # If target_email specified, search TO that address; otherwise broad search
            if "@" in target_email:
                search_criteria = f'(FROM "microsoft" TO "{target_email}" SINCE "{cutoff}")'
            else:
                search_criteria = f'(FROM "microsoft" SINCE "{cutoff}")'
            status, msg_ids = mail.search(None, search_criteria)

            if status == "OK" and msg_ids[0]:
                for msg_id in reversed(msg_ids[0].split()[-10:]):
                    if msg_id in seen_ids:
                        continue
                    seen_ids.add(msg_id)
                    try:
                        _, msg_data = mail.fetch(msg_id, "(RFC822)")
                        msg = email_lib.message_from_bytes(msg_data[0][1])
                        
                        # Skip emails older than min_timestamp
                        if min_timestamp > 0:
                            try:
                                date_str = msg.get("Date", "")
                                if date_str:
                                    msg_dt = parsedate_to_datetime(date_str)
                                    from datetime import timezone
                                    if msg_dt.tzinfo is None:
                                        msg_dt = msg_dt.replace(tzinfo=timezone.utc)
                                    msg_ts = msg_dt.timestamp()
                                    # Allow 30s tolerance (clock skew between servers)
                                    if msg_ts < min_timestamp - 30:
                                        continue
                            except:
                                pass  # Can't parse date, try anyway
                        
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() in ("text/plain", "text/html"):
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        body += payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                        else:
                            payload = msg.get_payload(decode=True)
                            if payload:
                                body += payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")

                        for pattern in [
                            r'>\s*(\d{6,8})\s*<', r'(?:security code|código|segurança)[:\s]*(\d{4,8})',
                            r'<td[^>]*>\s*(\d{6,8})\s*</td>', r'(?:^|\s)(\d{6,8})(?:\s|$)',
                        ]:
                            matches = re.findall(pattern, body, re.IGNORECASE)
                            if matches:
                                mail.logout()
                                return matches[0].strip()
                    except:
                        continue
            mail.logout()
        except:
            pass
        time.sleep(4)
    return None


def extract_email_content(html: str, service: str) -> dict | None:
    """Extract link or code from email HTML body based on service type."""
    html_lower = html.lower()

    # === CODE-BASED SERVICES ===
    if service == "temp_code":
        if "netflix" not in html_lower:
            return None

        # FORMATO NOVO: botão "Receber código" — extrai o link (Netflix envia link, não código direto)
        for btn_pat in [
            r'(?:receber\s*c[oó]digo|get\s*code|receive\s*code)[^<]{0,300}?href="(https?://[^"]+)"',
            r'href="(https?://[^"]+)"[^>]*>[^<]{0,80}(?:receber\s*c[oó]digo|get\s*code)',
        ]:
            m = re.findall(btn_pat, html, re.IGNORECASE | re.DOTALL)
            if m:
                link = m[0].replace("&amp;", "&").replace("&#x3D;", "=")
                return {"link": link}

        # FORMATO ANTIGO: código numérico direto no email
        def _is_likely_code(s):
            if re.match(r'^(19|20)\d{2}$', s):
                return False
            return True

        for pat in [
            r'style="[^"]*font-size:\s*(?:2[4-9]|3[0-9]|4[0-9])[^"]*"[^>]*>\s*(\d{4,8})\s*<',
            r'<td[^>]*>\s*(\d{4,8})\s*</td>',
            r'(?:código|code|access code)[^<]{0,50}?(\d{4,8})',
            r'<(?:p|span|div)[^>]*>\s*(\d{4,8})\s*</(?:p|span|div)>',
        ]:
            m = [x for x in re.findall(pat, html, re.IGNORECASE) if _is_likely_code(x)]
            if m:
                return {"code": m[0].strip()}

    if service == "netflix_disconnect":
        # 6-digit code from "Confirme a alteração da sua conta com este código"
        if "netflix" not in html_lower:
            return None
        for pat in [
            # Large styled code (most common in Netflix emails)
            r'style="[^"]*font-size:\s*(?:2[4-9]|3[0-9]|4[0-9]|5[0-9])[^"]*"[^>]*>\s*(\d{6})\s*<',
            r'<td[^>]*>\s*(\d{6})\s*</td>',
            # Code near keywords
            r'(?:código|code|alteração|confirm)[^<]{0,80}?(\d{6})',
            # Any standalone 6-digit number in large text
            r'>\s*(\d{6})\s*<',
        ]:
            m = re.findall(pat, html, re.IGNORECASE)
            if m:
                return {"code": m[0].strip()}

    if service == "prime_code":
        if not any(kw in html_lower for kw in ["amazon", "prime", "primevideo"]):
            return None
        for pat in [
            r'style="[^"]*font-size:\s*(?:2[4-9]|3[0-9]|4[0-9]|5[0-9])[^"]*"[^>]*>\s*(\d{4,8})\s*<',
            r'<td[^>]*>\s*(\d{6})\s*</td>',
            r'(?:código|code|verification|otp|verificação)[^<]{0,80}?(\d{4,8})',
            r'>\s*(\d{6})\s*<',
        ]:
            m = re.findall(pat, html, re.IGNORECASE)
            if m:
                return {"code": m[0].strip()}

    if service == "disney_code":
        if not any(kw in html_lower for kw in ["disney", "disneyplus"]):
            return None
        for pat in [
            r'style="[^"]*font-size:\s*(?:2[4-9]|3[0-9]|4[0-9]|5[0-9])[^"]*"[^>]*>\s*(\d{4,8})\s*<',
            r'<td[^>]*>\s*(\d{6})\s*</td>',
            r'(?:código|code|verification|otp|verificação|passcode)[^<]{0,80}?(\d{4,8})',
            r'>\s*(\d{6})\s*<',
        ]:
            m = re.findall(pat, html, re.IGNORECASE)
            if m:
                return {"code": m[0].strip()}

    # === LINK-BASED SERVICES ===
    if service == "globo_reset":
        if not any(kw in html_lower for kw in ["globo", "globoplay"]):
            return None
        all_links = re.findall(r'href="(https?://[^"]+)"', html, re.IGNORECASE)
        skip = ["unsubscribe", "privacy", ".png", ".jpg", ".gif", ".svg", "tracking", "beacon"]
        for raw in all_links:
            link = raw.replace("&amp;", "&").replace("&#x3D;", "=")
            ll = link.lower()
            if any(s in ll for s in skip):
                continue
            if any(kw in ll for kw in ["redefinir", "reset", "password", "senha", "recover", "account"]):
                return {"link": link}
        # Fallback: any globo link
        for raw in all_links:
            link = raw.replace("&amp;", "&")
            ll = link.lower()
            if any(s in ll for s in skip):
                continue
            if "globo" in ll:
                return {"link": link}

    # === NETFLIX LINK SERVICES (password_reset, household_update) ===
    if service in ("password_reset", "household_update"):
        if "netflix" not in html_lower:
            return None

        all_links = []
        for pat in [
            r'href="(https?://[^"]*netflix[^"]*)"',
            r'href="(https?://[^"]*nflxso[^"]*)"',
            r'(https?://www\.netflix\.com/[^\s<"\']+)',
        ]:
            all_links.extend(re.findall(pat, html, re.IGNORECASE))

        skip = ["unsubscribe", "privacy", "help.netflix", ".png", ".jpg", ".gif", ".svg", "tracking", "beacon", "notificationsettings", "comm_settings", "paymentpicker", "payment", "billing", "simplemember", "signup", "/create", "accountaccess"]
        relevant = {
            "password_reset": ["password", "reset", "redefin", "account/update"],
            "household_update": ["household", "residenc", "hogar", "travel/verify"],
        }
        kws = relevant.get(service, [])

        seen = set()
        for raw in all_links:
            link = raw.replace("&amp;", "&").replace("&#x3D;", "=")
            if link in seen:
                continue
            seen.add(link)
            ll = link.lower()
            if any(s in ll for s in skip):
                continue
            if any(k in ll for k in kws):
                return {"link": link}

        # SEM FALLBACK — se não achou link com keywords de household/residência, retorna None
        # Evita retornar links aleatórios da Netflix (signup, accountaccess, notificationsettings etc.)

    return None


# Keep backward compatibility alias
def extract_netflix_link(html: str, service: str) -> dict | None:
    return extract_email_content(html, service)


def is_imap_direct_email(email_addr: str) -> bool:
    """Check if this email should use IMAP direct search instead of MS login."""
    for pattern in IMAP_DIRECT_EMAILS:
        if re.match(pattern, email_addr.lower()):
            return True
    return False


def trigger_netflix_reset(email_addr: str, job_id: str) -> bool:
    """
    Dispara automaticamente o email de redefinição de senha na Netflix.
    Usa httpx para buscar o authURL e fazer o POST — sem browser.
    Retorna True se disparou com sucesso, False se falhou (não crítico).
    """
    try:
        import httpx

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Referer": "https://www.netflix.com/",
        }

        client = httpx.Client(follow_redirects=True, timeout=15, headers=headers)

        # Step 1: GET LoginHelp para pegar authURL e cookies
        r1 = client.get("https://www.netflix.com/LoginHelp")
        body1 = r1.text

        auth_match = re.search(r'"authURL"\s*:\s*"([^"]+)"', body1)
        if not auth_match:
            logger.warning(f"[{job_id}] trigger_reset: authURL não encontrado")
            return False

        raw_auth = auth_match.group(1)
        # Decodifica escapes unicode tipo \x2F -> /
        auth_url = raw_auth.encode().decode("unicode_escape")
        logger.info(f"[{job_id}] trigger_reset: authURL ok")

        # Step 2: POST do reset
        r2 = client.post(
            "https://www.netflix.com/LoginHelp",
            data={
                "action": "loginHelp",
                "withFields": "email",
                "authURL": auth_url,
                "nextPage": "",
                "email": email_addr,
                "mode": "loginHelp",
                "flow": "loginHelpFlow",
                "step": "emailAddressFeatureStep",
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://www.netflix.com",
                "Referer": "https://www.netflix.com/LoginHelp",
            },
        )

        # Netflix redireciona pra /LoginHelp?reset=true em sucesso
        final_url = str(r2.url)
        if "reset=true" in final_url or "emailSent" in final_url or "LoginHelp" in final_url:
            logger.info(f"[{job_id}] trigger_reset: email de reset disparado para {email_addr} ✓")
            return True
        elif "NotFound" in final_url:
            logger.warning(f"[{job_id}] trigger_reset: Netflix rejeitou (NotFound) — pode ser bot detection")
            return False
        else:
            logger.info(f"[{job_id}] trigger_reset: resposta={final_url[:80]}")
            return True

    except Exception as e:
        logger.warning(f"[{job_id}] trigger_reset error: {e} — continuando mesmo assim")


def process_job_imap_direct(job_id: str, email_addr: str, service: str):
    """Search for emails directly via IMAP on cinepremiu.com. No MS login needed."""
    patterns = EMAIL_PATTERNS.get(service, [])
    sender_keywords = IMAP_SENDER_PATTERNS.get(service, [])
    
    try:
        update_job(job_id, "connecting", method="imap", eta=5)
        logger.info(f"[{job_id}] IMAP connecting to {RECOVERY_IMAP_SERVER}...")
        
        mail = imaplib.IMAP4_SSL(RECOVERY_IMAP_SERVER, 993, timeout=15)
        mail.login(RECOVERY_EMAIL, RECOVERY_PASSWORD)
        mail.select("INBOX", readonly=True)
        
        update_job(job_id, "logged_in", method="imap", eta=3)
        update_job(job_id, "searching", method="imap", eta=2)
        
        cutoff = (datetime.now() - timedelta(minutes=SEARCH_MINUTES)).strftime("%d-%b-%Y")
        
        # Build search: TO + SINCE (strict)
        search_criteria = f'(TO "{email_addr}" SINCE "{cutoff}")'
        logger.info(f"[{job_id}] IMAP search: {search_criteria}")
        
        status, msg_ids = mail.search(None, search_criteria)
        
        if status != "OK" or not msg_ids[0]:
            logger.info(f"[{job_id}] No results with SINCE, trying last 7 days...")
            cutoff_broad = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
            search_criteria = f'(TO "{email_addr}" SINCE "{cutoff_broad}")'
            status, msg_ids = mail.search(None, search_criteria)
        
        if status != "OK" or not msg_ids[0]:
            mail.logout()
            logger.info(f"[{job_id}] IMAP: no emails found for {email_addr}")
            update_job(job_id, "not_found",
                message="Nenhum email encontrado. Reenvie a solicitação e tente novamente.")
            return
        
        all_ids = msg_ids[0].split()
        logger.info(f"[{job_id}] IMAP direct: {len(all_ids)} emails for {email_addr}")
        
        # Two-pass: subject match first (priority), then fallback (any sender match)
        recent_ids = list(reversed(all_ids[-15:]))
        subject_matched_ids = []
        fallback_ids = []
        
        for msg_id in recent_ids:
            try:
                _, msg_data = mail.fetch(msg_id, "(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
                header_raw = msg_data[0][1]
                header_msg = email_lib.message_from_bytes(header_raw)
                
                from_header = (header_msg.get("From", "") or "").lower()
                if sender_keywords and not any(kw in from_header for kw in sender_keywords):
                    continue
                
                subject_raw = header_msg.get("Subject", "") or ""
                subject = ""
                try:
                    for part_bytes, charset in decode_header(subject_raw):
                        if isinstance(part_bytes, bytes):
                            subject += part_bytes.decode(charset or "utf-8", errors="ignore")
                        else:
                            subject += str(part_bytes)
                except:
                    subject = subject_raw
                subject = subject.lower()
                
                if patterns and any(p in subject for p in patterns):
                    subject_matched_ids.append(msg_id)
                else:
                    fallback_ids.append(msg_id)
            except:
                continue
        
        logger.info(f"[{job_id}] IMAP direct: {len(subject_matched_ids)} subject match, {len(fallback_ids)} fallback")
        
        for msg_id in subject_matched_ids + fallback_ids:
            try:
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                msg = email_lib.message_from_bytes(msg_data[0][1])
                
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ct = part.get_content_type()
                        if ct in ("text/html", "text/plain"):
                            payload = part.get_payload(decode=True)
                            if payload:
                                charset = part.get_content_charset() or "utf-8"
                                body += payload.decode(charset, errors="ignore")
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        charset = msg.get_content_charset() or "utf-8"
                        body += payload.decode(charset, errors="ignore")
                
                if not body:
                    continue
                
                result = extract_email_content(body, service)
                if result:
                    expired = False
                    logger.info(f"[{job_id}] IMAP FOUND: {result} (expired={expired})")
                    mail.logout()
                    update_job(job_id, "found",
                        link=result.get("link"), code=result.get("code"),
                        method="imap", expired=expired)
                    return
            except Exception as e:
                logger.warning(f"[{job_id}] IMAP msg error: {e}")
                continue
        
        mail.logout()
        logger.info(f"[{job_id}] IMAP: no matching content found")
        update_job(job_id, "not_found",
            message="Nenhum email encontrado nos últimos 15 minutos. Reenvie a solicitação e tente novamente.")
    
    except Exception as e:
        logger.error(f"[{job_id}] IMAP direct error: {traceback.format_exc()}")
        update_job(job_id, "error", message=f"Erro IMAP: {str(e)[:80]}")


def fast_login(page, email_addr: str, job_id: str) -> bool:
    """Fast login to Microsoft account. Returns True if successful."""
    logger.info(f"[{job_id}] Fast login: {email_addr}")
    
    page.goto("https://login.live.com/", timeout=20000, wait_until="domcontentloaded")
    
    # Email
    page.wait_for_selector("input[type=email]", timeout=10000)
    page.fill("input[type=email]", email_addr)
    page.keyboard.press("Enter")
    time.sleep(3)
    
    # After entering email, MS can show different pages:
    # 1) Password field directly
    # 2) "Verify your email" + "Use your password" link  
    # 3) Account doesn't exist error
    # 4) Phone verification ("Verifique seu número de telefone") with "Outras maneiras de entrar"
    #    → leads to "Entrar de outra forma" with "Use sua senha"
    
    # Check error first
    try:
        body = page.inner_text("body").lower()
        if "doesn't exist" in body or "não existe" in body or "that microsoft account doesn" in body:
            logger.error(f"[{job_id}] Account doesn't exist")
            return False
    except:
        body = ""
    
    # === PHONE VERIFICATION SCREEN (before password) ===
    # MS shows "Verifique seu número de telefone" / "Verify your phone number"
    # with "Outras maneiras de entrar" / "Other ways to sign in" link
    # Clicking it leads to "Entrar de outra forma" with "Use sua senha"
    _phone_screen_keywords = ["verifique seu número", "verify your phone", "número de telefone",
                              "phone number", "enviaremos um código para"]
    if any(kw in body for kw in _phone_screen_keywords):
        logger.info(f"[{job_id}] Phone verification screen detected (pre-login), looking for alternatives...")
        
        # Step 1: Click "Outras maneiras de entrar" / "Other ways to sign in"
        _found_alt = False
        for text in ["Outras maneiras de entrar", "Other ways to sign in", 
                      "Sign in another way", "Outras formas de entrar",
                      "I can't use this right now", "Não posso usar isso agora"]:
            try:
                link = page.get_by_text(text, exact=False)
                if link.is_visible(timeout=2000):
                    link.click()
                    logger.info(f"[{job_id}] Clicked '{text}'")
                    time.sleep(3)
                    _found_alt = True
                    break
            except:
                continue
        
        if not _found_alt:
            logger.warning(f"[{job_id}] Could not find 'Outras maneiras de entrar', trying links...")
            # Try any link/button that might lead to alternatives
            try:
                links = page.locator("a, button").all()
                for l in links:
                    try:
                        lt = l.inner_text().lower().strip()
                        if "outra" in lt or "other" in lt or "different" in lt:
                            l.click()
                            logger.info(f"[{job_id}] Clicked alt link: '{lt}'")
                            time.sleep(3)
                            _found_alt = True
                            break
                    except:
                        continue
            except:
                pass
        
        # Step 2: Now on "Entrar de outra forma" — click "Use sua senha"
        if _found_alt:
            body = page.inner_text("body").lower()
            logger.info(f"[{job_id}] Alt sign-in page: {body[:200]}")
    
    # === TRY "Use your password" / "Use sua senha" ===
    # Works both for direct prompt AND after phone bypass above
    for text in ["Use your password", "Use sua senha", "Usar senha", "Use a password",
                 "Sign in with a password", "Entrar com senha"]:
        try:
            link = page.get_by_text(text, exact=False)
            if link.is_visible(timeout=1500):
                link.click()
                logger.info(f"[{job_id}] Clicked '{text}'")
                time.sleep(2)
                break
        except:
            continue
    
    # Wait for password field
    try:
        pwd = page.locator("input[type=password]")
        pwd.wait_for(timeout=8000)
    except:
        logger.error(f"[{job_id}] Password field not found")
        try:
            page.screenshot(path=f"/tmp/login_fail_{job_id}.png")
            body_now = page.inner_text("body").lower()
            logger.error(f"[{job_id}] Page text: {body_now[:300]}")
        except:
            pass
        return False
    
    # Try primary password first, then alternative
    for attempt, password in enumerate([HOTMAIL_PASSWORD, HOTMAIL_PASSWORD_ALT]):
        pwd = page.locator("input[type=password]")
        pwd.fill(password)
        page.keyboard.press("Enter")
        time.sleep(3)
        
        try:
            body = page.inner_text("body").lower()
            if "incorrect" in body or "incorreta" in body or "contraseña incorrecta" in body:
                if attempt == 0:
                    logger.info(f"[{job_id}] Primary password failed, trying alternative...")
                    try:
                        pwd2 = page.locator("input[type=password]")
                        pwd2.wait_for(timeout=3000)
                        pwd2.fill("")
                    except:
                        pass
                    continue
                else:
                    logger.error(f"[{job_id}] Both passwords failed")
                    return False
            else:
                if attempt == 1:
                    logger.info(f"[{job_id}] Alternative password worked!")
                return True
        except:
            return True
    
    return False


def _try_skip_security_prompt(page, job_id: str) -> bool:
    """
    Quando MS mostra 'proteja sua conta' / 'identity/confirm' / 'proofs',
    ao invés de tentar clicar botões, vai direto pro Outlook.
    Retorna True se redirecionou com sucesso E tá realmente no Outlook mail.
    """
    def _is_security_page(u):
        return any(x in u for x in ["identity/confirm", "proofs", "proteja", "protect"])
    
    def _try_redirect():
        logger.info(f"[{job_id}] Security prompt, tentando redirect pro Outlook...")
        
        # Primeiro, tentar clicar botões de skip na página de security (Remind me later, Skip, etc)
        for skip_text in ["Remind me later", "Lembrar mais tarde", "Skip", "Pular", "Cancel", "Cancelar", 
                          "I want to setup a different method", "Looks good", "Parece bom"]:
            try:
                btn = page.get_by_role("button", name=skip_text)
                if btn.is_visible(timeout=1000):
                    btn.click()
                    logger.info(f"[{job_id}] Clicou botão '{skip_text}' na security page")
                    time.sleep(3)
                    break
            except:
                continue
        # Tentar links de skip
        for skip_text in ["remind me later", "lembrar mais tarde", "skip for now", "pular por agora"]:
            try:
                link = page.locator(f"a:has-text('{skip_text}')").first
                if link.is_visible(timeout=1000):
                    link.click()
                    logger.info(f"[{job_id}] Clicou link '{skip_text}' na security page")
                    time.sleep(3)
                    break
            except:
                continue
        # Tentar #iCancel, #iLooksGood
        for sel in ["#iCancel", "#iLooksGood", "#iLandingViewAction", "#CancelLinkButton",
                     "a[id*='cancel']", "a[id*='Cancel']", "a[id*='skip']", "a[id*='Skip']"]:
            try:
                elem = page.locator(sel)
                if elem.is_visible(timeout=1000):
                    elem.click()
                    logger.info(f"[{job_id}] Clicou '{sel}' na security page")
                    time.sleep(3)
                    break
            except:
                continue
        
        # Checar se saiu da security page
        url_now = page.url.lower()
        if "outlook.live.com/mail" in url_now:
            logger.info(f"[{job_id}] Skip funcionou! Já está no Outlook.")
            return True
        if not _is_security_page(url_now) and "login.live" not in url_now and "microsoft-365" not in url_now:
            logger.info(f"[{job_id}] Skip funcionou, URL: {page.url}")
            # Agora navegar pro Outlook
        
        # Tentar múltiplas URLs do Outlook
        outlook_urls = [
            "https://outlook.live.com/mail/",
            "https://outlook.live.com/mail/0/",
            "https://outlook.live.com/owa/",
        ]
        
        for outlook_url in outlook_urls:
            try:
                logger.info(f"[{job_id}] Tentando redirect para {outlook_url}...")
                page.goto(outlook_url, timeout=25000, wait_until="domcontentloaded")
                time.sleep(6)
                final_url = page.url.lower()
                
                _is_marketing = "microsoft-365" in final_url or "microsoft.com/en" in final_url or "deeplink" in final_url
                if ("outlook.live.com/mail" in final_url or "outlook.live.com/owa" in final_url) and not _is_marketing:
                    # Verifica se tem elementos do Outlook
                    try:
                        has_inbox = page.locator("[role='option'], [aria-label*='earch'], [aria-label*='esquis'], button[aria-label*='New mail'], button[aria-label*='Nova']").first.is_visible(timeout=3000)
                        if has_inbox:
                            logger.info(f"[{job_id}] Redirect to Outlook OK! Inbox confirmed via {outlook_url}")
                            return True
                    except:
                        pass
                    # SEM confirmação de inbox — NÃO retornar True!
                    # Isso causa falso positivo (URL match mas redirect pra marketing depois)
                    logger.warning(f"[{job_id}] URL match mas inbox não confirmado via {outlook_url} — continuando...")
                    # Tentar a próxima URL antes de desistir
                elif _is_marketing:
                    logger.warning(f"[{job_id}] Redirect caiu na página marketing MS365: {final_url}")
                else:
                    logger.warning(f"[{job_id}] Redirect para {outlook_url} falhou, caiu em: {final_url}")
                    # Se caiu na identity/confirm de novo, tenta clicar skip antes de tentar próxima URL
                    if _is_security_page(final_url):
                        for skip_sel in ["#iCancel", "#iLooksGood", "#CancelLinkButton"]:
                            try:
                                elem = page.locator(skip_sel)
                                if elem.is_visible(timeout=1000):
                                    elem.click()
                                    time.sleep(3)
                                    break
                            except:
                                continue
            except Exception as e:
                logger.warning(f"[{job_id}] Redirect {outlook_url} exception: {str(e)[:100]}")
        
        logger.warning(f"[{job_id}] Todas as tentativas de redirect falharam. URL final: {page.url}")
        # Tentar voltar pra identity/confirm pra que handle_verification possa agir
        try:
            page.go_back()
            time.sleep(3)
            back_url = page.url.lower()
            logger.info(f"[{job_id}] Voltou pra: {back_url}")
            if not _is_security_page(back_url):
                # Tenta navegar direto
                page.goto("https://account.live.com/identity/confirm", timeout=15000, wait_until="domcontentloaded")
                time.sleep(3)
                logger.info(f"[{job_id}] Navegou pra identity/confirm: {page.url}")
        except Exception as e:
            logger.warning(f"[{job_id}] Erro ao voltar pra identity: {e}")
        return False

    url = page.url.lower()
    if _is_security_page(url):
        return _try_redirect()
    
    # Also check body text
    try:
        body = page.inner_text("body").lower()
        if any(x in body for x in ["proteja sua conta", "protect your account", "verify your identity"]):
            return _try_redirect()
    except:
        pass
    return False


def handle_post_login(page, job_id: str) -> str:
    """
    Handle all post-login screens (stay signed in, privacy, abuse, verification).
    Returns: "ok", "abuse", "verification", "error"
    """
    # Quick dismiss common prompts
    for _ in range(3):
        url = page.url.lower()
        
        if "abuse" in url:
            return "abuse"
        
        if "identity/confirm" in url or "proofs" in url:
            # NÃO tentar pular — ir direto pra handle_verification
            logger.info(f"[{job_id}] identity/confirm detectado, indo pra verificação...")
            return "verification"
        
        if "outlook.live.com" in url and "microsoft-365" not in url and "microsoft.com/en" not in url:
            return "ok"
        
        # Try clicking dismiss buttons
        clicked = False
        for sel in ["#idSIButton9", "#idBtn_Back", "#acceptButton"]:
            try:
                btn = page.locator(sel)
                if btn.is_visible(timeout=1000):
                    btn.click(no_wait_after=True, timeout=3000)
                    clicked = True
                    break
            except:
                continue
        
        if not clicked:
            for text in ["Yes", "No", "OK", "Accept", "Continue", "Next", "Aceitar", "Continuar"]:
                try:
                    btn = page.get_by_role("button", name=text)
                    if btn.is_visible(timeout=800):
                        btn.click(no_wait_after=True, timeout=3000)
                        clicked = True
                        break
                except:
                    continue
        
        time.sleep(2)
    
    # Final check
    url = page.url.lower()
    body = ""
    try:
        body = page.inner_text("body").lower()
    except:
        pass
    
    if "abuse" in url:
        return "abuse"
    if "identity" in url or "proofs" in url:
        logger.info(f"[{job_id}] identity/proofs na final check, indo pra verificação...")
        return "verification"
    # Also detect verification by page content
    if "verify your email" in body or "verificar seu email" in body or \
       "protect your account" in body or "proteja sua conta" in body:
        logger.info(f"[{job_id}] Página de verificação detectada pelo conteúdo")
        return "verification"
    
    return "ok"


def handle_verification(page, job_id: str, username: str) -> bool:
    """Handle MS identity verification with recovery email."""
    
    try:
        # Screenshot for debugging
        try:
            page.screenshot(path=f"/tmp/verify_{job_id}.png")
        except:
            pass
        
        # Log what we see
        body_text = page.inner_text("body").lower()
        logger.info(f"[{job_id}] Verification page: {body_text[:300]}")
        url = page.url.lower()
        logger.info(f"[{job_id}] Verification URL: {url}")
        
        # === PHONE VERIFICATION BYPASS ===
        # If MS shows phone verification (e.g. "verify your phone number", "text *****54"),
        # click "Use your password" / "Use sua senha" to skip it
        phone_keywords = ["verify your phone", "verifique seu número", "número de telefone",
                          "phone number", "text *", "sms *", "enviaremos um código para *"]
        _is_phone_only = any(kw in body_text for kw in phone_keywords)
        if _is_phone_only:
            logger.info(f"[{job_id}] Phone verification detected, looking for password bypass...")
            _phone_bypassed = False
            
            # Strategy 1: Try "Use your password" links
            for text in ["Use your password", "Use sua senha", "Usar senha", "Use a password",
                         "Sign in with a password", "Entrar com senha", "Sign in a different way",
                         "Entrar de outra forma"]:
                try:
                    link = page.get_by_text(text)
                    if link.is_visible(timeout=2000):
                        link.click()
                        logger.info(f"[{job_id}] Clicked '{text}' to bypass phone verification")
                        time.sleep(3)
                        
                        # If password field appeared, fill it and continue
                        try:
                            pwd = page.locator("input[type=password]")
                            if pwd.is_visible(timeout=3000):
                                pwd.fill(HOTMAIL_PASSWORD)
                                page.keyboard.press("Enter")
                                logger.info(f"[{job_id}] Entered password after phone bypass")
                                time.sleep(4)
                                
                                final_url = page.url.lower()
                                if "identity" not in final_url and "proofs" not in final_url:
                                    logger.info(f"[{job_id}] Phone bypass + password worked!")
                                    return True
                                else:
                                    body_text = page.inner_text("body").lower()
                                    logger.info(f"[{job_id}] After phone bypass still on verification, continuing...")
                                    _phone_bypassed = True
                        except:
                            pass
                        break
                except:
                    continue
            
            # Strategy 2: Try "I don't have these any more" to reach email recovery
            if not _phone_bypassed:
                for text in ["I don't have these any more", "Não tenho mais acesso a esses",
                             "Não tenho acesso", "I can't use any of these",
                             "I don't have access", "Não tenho mais"]:
                    try:
                        link = page.get_by_text(text, exact=False)
                        if link.is_visible(timeout=2000):
                            link.click()
                            logger.info(f"[{job_id}] Clicked '{text}' to try alternative verification")
                            time.sleep(4)
                            
                            new_body = page.inner_text("body").lower()
                            new_url = page.url.lower()
                            logger.info(f"[{job_id}] After 'no access': {new_url} | {new_body[:200]}")
                            
                            # Check if we now have email option or password option
                            if "email" in new_body or "@" in new_body or "password" in new_body or "senha" in new_body:
                                body_text = new_body
                                _phone_bypassed = True
                                logger.info(f"[{job_id}] Got alternative verification options!")
                            elif "recover" in new_url or "resetpw" in new_url or "acsr" in new_url:
                                # MS sent us to account recovery - can't help here
                                logger.warning(f"[{job_id}] Redirected to account recovery, can't bypass")
                            break
                    except:
                        continue
            
            # If phone-only and no bypass worked, don't try email flow (will fail on radio buttons)
            if not _phone_bypassed:
                logger.warning(f"[{job_id}] Phone-only verification, no bypass available. Giving up.")
                return False
        
        # === RESOLVE RECOVERY EMAIL ===
        # Extract masked email from page (e.g. "te*****@gmail.com" or "te*****@gm" or "ca***@cinepremiu.com")
        # MS may truncate the domain too, so we accept partial domains
        masked_match = re.search(r'(\w{1,10})\*+@(\w[\w.]*)', body_text)
        recovery = f"{username}@{RECOVERY_DOMAIN}"  # default
        
        if masked_match:
            masked_prefix = masked_match.group(1)
            masked_domain = masked_match.group(2).rstrip(".")
            logger.info(f"[{job_id}] MS shows masked email: {masked_prefix}***@{masked_domain}")
            
            # Always try to resolve — even if username matches, could be a different recovery email
            logger.info(f"[{job_id}] Resolving masked email '{masked_prefix}***@{masked_domain}'...")
            resolved = resolve_recovery_email(masked_prefix, masked_domain, job_id)
            if resolved:
                recovery = resolved
            elif "cinepremiu" in masked_domain:
                recovery = f"catchall@cinepremiu.com"
                logger.info(f"[{job_id}] Domain is cinepremiu, using catchall")
            else:
                # Last resort: try simple guess
                if "." in masked_domain and masked_domain.endswith(".com"):
                    recovery = f"{masked_prefix}@{masked_domain}"
                else:
                    # Domain is truncated (e.g. "gm"), can't guess
                    recovery = f"{masked_prefix}@{masked_domain}"
                logger.warning(f"[{job_id}] Could not resolve, guessing: {recovery}")
        
        logger.info(f"[{job_id}] Verification: using {recovery}")
        
        # === FLOW A: "Help us protect your account" with radio buttons ===
        has_radio = "protect your account" in body_text or "proteja sua conta" in body_text or "help us" in body_text
        has_email_radio = "cinepremiu" in body_text or "email" in body_text
        
        if has_radio and has_email_radio:
            logger.info(f"[{job_id}] Flow A: Radio button verification")
            
            # Select the email radio button (first radio, which is the email option)
            try:
                # Click on the radio button or the text next to it
                email_option = page.locator("input[type=radio]").first
                if email_option.is_visible(timeout=2000):
                    email_option.click(force=True)
                    logger.info(f"[{job_id}] Selected email radio button")
                    time.sleep(0.5)
            except:
                # Try clicking the text label instead
                try:
                    page.locator("text=/Email.*cinepremiu|Email.*@/i").first.click()
                    logger.info(f"[{job_id}] Clicked email label")
                    time.sleep(0.5)
                except:
                    logger.warning(f"[{job_id}] Could not find email radio")
            
            # Click Next
            for text in ["Next", "Próximo", "Continue", "Continuar"]:
                try:
                    btn = page.get_by_role("button", name=text)
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        logger.info(f"[{job_id}] Clicked: {text}")
                        break
                except:
                    continue
            
            time.sleep(5)
            
            # Now MS should show a text field to type the full email address
            new_body = page.inner_text("body").lower()
            logger.info(f"[{job_id}] After radio Next: {new_body[:200]}")
            
            # Check if it now wants us to type the email
            text_input = None
            for sel in ["input[type=email]", "input[type=text]:not([name=loginfmt])",
                         "input[id*='iProof']", "input[id*='iOttText']",
                         "input[name*='iProofEmail']", "input[placeholder*='@']",
                         "input[placeholder*='email']"]:
                try:
                    inp = page.locator(sel).first
                    if inp.is_visible(timeout=2000):
                        text_input = inp
                        logger.info(f"[{job_id}] Found text input: {sel}")
                        break
                except:
                    continue
            
            _send_code_ts = time.time()  # timestamp before sending code, to filter old codes
            if text_input:
                text_input.fill(recovery)
                logger.info(f"[{job_id}] Typed recovery email: {recovery}")
                time.sleep(0.5)
                
                # Click Send code
                _send_code_ts = time.time()
                for text in ["Send code", "Enviar código", "Get code", "Obter código"]:
                    try:
                        btn = page.get_by_role("button", name=text)
                        if btn.is_visible(timeout=2000):
                            btn.click()
                            logger.info(f"[{job_id}] Clicked: {text}")
                            break
                    except:
                        continue
                else:
                    page.keyboard.press("Enter")
                
                time.sleep(4)
            
            # After Send code, check if page actually advanced
            new_url = page.url.lower()
            new_body = page.inner_text("body").lower()
            logger.info(f"[{job_id}] After send code: URL={new_url}, body={new_body[:150]}")
            
            # Check if still on radio button page (send code failed — wrong email)
            if "iproof0" in page.content().lower() or "iproofemail" in page.content().lower():
                # Check for error message
                if "doesn't match" in new_body or "incorrect" in new_body or "try again" in new_body or "não corresponde" in new_body:
                    logger.error(f"[{job_id}] Recovery email rejected by MS")
                    return False
                # Page didn't change — email probably wrong
                radio_still = page.locator("input[type=radio]").count()
                if radio_still > 0:
                    logger.error(f"[{job_id}] Page didn't advance after Send code — recovery email likely wrong")
                    return False
            
            # Check if we're past verification already
            if "identity" not in new_url and "proofs" not in new_url and "abuse" not in new_url:
                logger.info(f"[{job_id}] Verification passed!")
                return True
            
            # Code was sent — wait for it via IMAP and enter it
            # Use _send_code_ts to only accept codes newer than when we clicked Send
            logger.info(f"[{job_id}] Code sent! Waiting for IMAP delivery...")
            code = get_ms_verification_code(recovery, job_id, max_wait=55, min_timestamp=_send_code_ts)
            if not code:
                logger.warning(f"[{job_id}] Code not received via IMAP for {recovery}")
                
                # === RETRY with other candidates from known list ===
                _all_candidates = resolve_all_recovery_emails(masked_prefix, masked_domain, job_id) if masked_match else []
                _remaining = [c for c in _all_candidates if c != recovery]
                
                if _remaining:
                    logger.info(f"[{job_id}] Trying {len(_remaining)} other candidates: {_remaining}")
                    
                    for alt_recovery in _remaining:
                        logger.info(f"[{job_id}] Retrying with: {alt_recovery}")
                        
                        # Click "Use a different verification option" or similar to go back
                        _went_back = False
                        for back_text in ["Use a different verification option", "Usar outra opção",
                                          "I didn't get a code", "Não recebi um código",
                                          "use a di", "didn't get"]:
                            try:
                                link = page.get_by_text(back_text, exact=False)
                                if link.is_visible(timeout=2000):
                                    link.click()
                                    logger.info(f"[{job_id}] Clicked: '{back_text}'")
                                    time.sleep(3)
                                    _went_back = True
                                    break
                            except:
                                continue
                        
                        # After going back, we may land on radio button page again
                        # Need to: select radio → click Next → then fill email input
                        try:
                            _radio = page.locator("input[type=radio]").first
                            if _radio.is_visible(timeout=2000):
                                _radio.click(force=True)
                                logger.info(f"[{job_id}] Re-selected email radio")
                                time.sleep(0.5)
                                for next_text in ["Next", "Próximo", "Continue", "Continuar"]:
                                    try:
                                        btn = page.get_by_role("button", name=next_text)
                                        if btn.is_visible(timeout=2000):
                                            btn.click()
                                            logger.info(f"[{job_id}] Clicked: {next_text}")
                                            break
                                    except:
                                        continue
                                time.sleep(4)
                        except:
                            pass
                        
                        # Find email text input (NOT radio)
                        _alt_input = None
                        for sel in ["input[type=email]", "input[type=text]:not([name=loginfmt])",
                                     "input[name*='iProofEmail']", "input[placeholder*='@']",
                                     "input[placeholder*='email']"]:
                            try:
                                inp = page.locator(sel).first
                                if inp.is_visible(timeout=2000):
                                    _alt_input = inp
                                    break
                            except:
                                continue
                        
                        if not _alt_input:
                            logger.warning(f"[{job_id}] Could not find email input for retry, skipping {alt_recovery}")
                            continue
                        
                        _alt_input.fill("")
                        _alt_input.fill(alt_recovery)
                        logger.info(f"[{job_id}] Typed alt recovery: {alt_recovery}")
                        time.sleep(0.5)
                        
                        _alt_send_ts = time.time()
                        for text in ["Send code", "Enviar código", "Get code", "Obter código"]:
                            try:
                                btn = page.get_by_role("button", name=text)
                                if btn.is_visible(timeout=2000):
                                    btn.click()
                                    logger.info(f"[{job_id}] Clicked: {text}")
                                    break
                            except:
                                continue
                        else:
                            page.keyboard.press("Enter")
                        
                        time.sleep(4)
                        
                        logger.info(f"[{job_id}] Waiting for code via {alt_recovery}...")
                        code = get_ms_verification_code(alt_recovery, job_id, max_wait=40, min_timestamp=_alt_send_ts)
                        if code:
                            recovery = alt_recovery
                            logger.info(f"[{job_id}] Code received via {alt_recovery}! code={code}")
                            break
                        else:
                            logger.warning(f"[{job_id}] Code not received for {alt_recovery}, trying next...")
                
                if not code:
                    logger.error(f"[{job_id}] Code not received via IMAP (tried all candidates)")
                    return False
            
            logger.info(f"[{job_id}] Got code: {code}")
            
            # Wait for the code input to appear (page may need time to transition)
            code_input = None
            for attempt in range(5):
                for sel in ["input[id='iOttText']", "input[id*='iOttText']", 
                             "input[type=tel]", "input[name*='iOttText']",
                             "input[name*='otc']", "input[id*='otc']",
                             "input[name*='code']", "input[id*='code']",
                             "input[aria-label*='code']", "input[aria-label*='Code']",
                             "input[aria-label*='código']",
                             "input[placeholder*='code']", "input[placeholder*='código']"]:
                    try:
                        inp = page.locator(sel).first
                        if inp.is_visible(timeout=1000):
                            code_input = inp
                            break
                    except:
                        continue
                if code_input:
                    break
                logger.info(f"[{job_id}] Code input not found yet, attempt {attempt+1}/5, waiting...")
                time.sleep(2)
            
            # Fallback: try any visible text/number input that is NOT the email field
            if not code_input:
                logger.info(f"[{job_id}] Trying fallback: any visible input field")
                for sel in ["input[type=text]", "input[type=number]", "input[type=tel]"]:
                    try:
                        inputs = page.locator(sel).all()
                        for inp in inputs:
                            if inp.is_visible() and inp.get_attribute("value") in ["", None]:
                                val = inp.get_attribute("id") or inp.get_attribute("name") or "unknown"
                                logger.info(f"[{job_id}] Found empty input: {val}")
                                code_input = inp
                                break
                    except:
                        continue
                    if code_input:
                        break
            
            if not code_input:
                # Last resort: dump page info for debugging
                all_inputs = page.locator("input").all()
                for inp in all_inputs:
                    try:
                        attrs = f"id={inp.get_attribute('id')} name={inp.get_attribute('name')} type={inp.get_attribute('type')} visible={inp.is_visible()}"
                        logger.info(f"[{job_id}] Input on page: {attrs}")
                    except:
                        pass
            
            if code_input:
                code_input.fill("")
                time.sleep(0.3)
                code_input.fill(code)
                logger.info(f"[{job_id}] Entered code: {code}")
                time.sleep(0.5)
                
                clicked_verify = False
                for text in ["Verify", "Next", "Verificar", "Próximo", "Submit"]:
                    try:
                        btn = page.get_by_role("button", name=text)
                        if btn.is_visible(timeout=2000):
                            btn.click()
                            logger.info(f"[{job_id}] Clicked verify button: {text}")
                            clicked_verify = True
                            break
                    except:
                        continue
                
                if not clicked_verify:
                    # Try input[type=submit]
                    try:
                        submit = page.locator("input[type=submit]").first
                        if submit.is_visible(timeout=1000):
                            submit.click()
                            logger.info(f"[{job_id}] Clicked submit input")
                            clicked_verify = True
                    except:
                        pass
                
                if not clicked_verify:
                    page.keyboard.press("Enter")
                    logger.info(f"[{job_id}] Pressed Enter as fallback")
                
                time.sleep(4)
                
                final_url = page.url.lower()
                final_body = page.inner_text("body").lower()[:200]
                logger.info(f"[{job_id}] After verify: url={final_url}, body={final_body}")
                
                if "identity" not in final_url and "proofs" not in final_url:
                    logger.info(f"[{job_id}] Verification completed after code!")
                    return True
                else:
                    # Check for error messages
                    error_texts = ["incorrect", "wrong", "invalid", "expired", "incorreto", "inválido", "expirado", "try again", "tente novamente"]
                    if any(e in final_body for e in error_texts):
                        logger.warning(f"[{job_id}] Code was rejected, retrying...")
                    else:
                        logger.warning(f"[{job_id}] Still on verification, page body: {final_body[:300]}")
                    
                    # Retry: click "Send code" again and wait for a NEW code (ignore old one)
                    for retry_text in ["Send code", "Enviar código", "Send", "Enviar"]:
                        try:
                            retry_btn = page.get_by_role("button", name=retry_text)
                            if retry_btn.is_visible(timeout=1500):
                                retry_btn.click()
                                logger.info(f"[{job_id}] Retry: clicked '{retry_text}', waiting for new code...")
                                _retry_ts = time.time()
                                time.sleep(10)
                                # Get new code — must be newer than retry click
                                new_code = get_ms_verification_code(recovery, job_id, max_wait=55, min_timestamp=_retry_ts)
                                if new_code and new_code != code:
                                    code_input2 = page.locator("input[type=tel], input[type=number], input[type=text][id*='iOttText'], input[id*='iOttText']").first
                                    if code_input2.is_visible(timeout=2000):
                                        code_input2.fill("")
                                        code_input2.fill(new_code)
                                        logger.info(f"[{job_id}] Retry: entered new code: {new_code}")
                                        time.sleep(0.5)
                                        for vtext in ["Verify", "Next", "Verificar", "Próximo", "Submit"]:
                                            try:
                                                vbtn = page.get_by_role("button", name=vtext)
                                                if vbtn.is_visible(timeout=1000):
                                                    vbtn.click()
                                                    break
                                            except:
                                                continue
                                        time.sleep(4)
                                        final_url2 = page.url.lower()
                                        if "identity" not in final_url2 and "proofs" not in final_url2:
                                            logger.info(f"[{job_id}] Retry: verification completed!")
                                            return True
                                elif new_code == code:
                                    logger.warning(f"[{job_id}] Retry: got same code {code} again, MS may not have sent new one")
                                break
                        except:
                            continue
                    
                    logger.error(f"[{job_id}] Still on verification page after retry")
            else:
                logger.error(f"[{job_id}] Code input field not found")
        
        # === FLOW B: Direct email input (no radio buttons) ===
        else:
            logger.info(f"[{job_id}] Flow B: Direct email verification")
            
            text_input = None
            for sel in ["input[type=email]:not([name=loginfmt])", "input[id*='iProof']",
                         "input[id*='iOttText']", "input[placeholder*='@']",
                         "input[type=text]:not([name=loginfmt])"]:
                try:
                    inp = page.locator(sel).first
                    if inp.is_visible(timeout=2000):
                        text_input = inp
                        logger.info(f"[{job_id}] Found input: {sel}")
                        break
                except:
                    continue
            
            if text_input:
                text_input.fill(recovery)
                logger.info(f"[{job_id}] Filled: {recovery}")
                time.sleep(0.5)
            
            for text in ["Send code", "Enviar código", "Get code", "Obter código",
                          "Next", "Próximo", "Continue", "Continuar"]:
                try:
                    btn = page.get_by_role("button", name=text)
                    if btn.is_visible(timeout=1500):
                        btn.click()
                        logger.info(f"[{job_id}] Clicked: {text}")
                        break
                except:
                    continue
            else:
                page.keyboard.press("Enter")
            
            time.sleep(4)
            
            new_url = page.url.lower()
            if "identity" not in new_url and "proofs" not in new_url:
                logger.info(f"[{job_id}] Verification passed!")
                return True
        
        # === Wait for code via IMAP ===
        new_body = page.inner_text("body").lower()
        needs_code = any(kw in new_body for kw in [
            "enter code", "inserir código", "enter the code", "digite o código",
            "code we sent", "código que enviamos", "verify", "verificar"
        ])
        
        if needs_code:
            logger.info(f"[{job_id}] Waiting for MS verification code via IMAP...")
            code = get_ms_verification_code(recovery, job_id, max_wait=50)
            if not code:
                logger.error(f"[{job_id}] Code not received via IMAP")
                return False
            
            logger.info(f"[{job_id}] Got code: {code}")
            
            # Find code input with retries
            code_input = None
            for attempt in range(5):
                for sel in ["input[id='iOttText']", "input[id*='iOttText']",
                             "input[type=tel]", "input[name*='otc']", "input[id*='otc']",
                             "input[name*='code']", "input[id*='code']",
                             "input[aria-label*='code']", "input[aria-label*='Code']",
                             "input[placeholder*='code']", "input[placeholder*='código']"]:
                    try:
                        inp = page.locator(sel).first
                        if inp.is_visible(timeout=1000):
                            code_input = inp
                            break
                    except:
                        continue
                if code_input:
                    break
                time.sleep(2)
            
            if not code_input:
                # Fallback: any empty visible input
                for sel in ["input[type=text]", "input[type=number]", "input[type=tel]"]:
                    try:
                        inputs = page.locator(sel).all()
                        for inp in inputs:
                            if inp.is_visible() and inp.get_attribute("value") in ["", None]:
                                code_input = inp
                                break
                    except:
                        continue
                    if code_input:
                        break
            
            if code_input:
                code_input.fill("")
                time.sleep(0.3)
                code_input.fill(code)
                logger.info(f"[{job_id}] Entered code")
            else:
                logger.error(f"[{job_id}] Code input not found in Flow B")
            
            # Submit code
            for text in ["Verify", "Next", "Verificar", "Próximo"]:
                try:
                    btn = page.get_by_role("button", name=text)
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        break
                except:
                    continue
            else:
                page.keyboard.press("Enter")
            
            time.sleep(4)
        
        # Final check
        final_url = page.url.lower()
        if "identity" not in final_url and "proofs" not in final_url:
            logger.info(f"[{job_id}] Verification completed!")
            return True
        
        logger.error(f"[{job_id}] Still on verification page: {final_url}")
        try:
            page.screenshot(path=f"/tmp/verify_fail_{job_id}.png")
        except:
            pass
        return False
        
    except Exception as e:
        logger.error(f"[{job_id}] Verification error: {e}")
        return False


def _solve_captcha_external(email: str, password: str, job_id: str) -> bool:
    """
    Chama o serviço externo de CAPTCHA (captcha_service.py rodando na máquina Windows).
    Se o serviço não estiver disponível, tenta o UC local como fallback.
    """
    # URL hardcoded + env override
    CAPTCHA_NGROK = "https://liqueur-detract-stream.ngrok-free.dev"
    captcha_url = os.environ.get("CAPTCHA_SERVICE_URL", "").strip().rstrip("/") or CAPTCHA_NGROK
    
    logger.info(f"[{job_id}] Chamando serviço externo: {captcha_url}/solve")
    try:
        import json as _json
        payload = _json.dumps({
            "email": email,
            "password": password,
            "job_id": job_id,
        }).encode()
        req = urllib.request.Request(
            f"{captcha_url}/solve",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "ngrok-skip-browser-warning": "true",
            },
            method="POST",
        )
        # Timeout alto: CAPTCHA pode demorar até 3 min
        resp = urllib.request.urlopen(req, timeout=200)
        result = _json.loads(resp.read().decode())
        solved = result.get("solved", False)
        msg = result.get("message", "")
        logger.info(f"[{job_id}] Serviço externo: solved={solved}, msg={msg}")
        return solved
    except Exception as e:
        logger.error(f"[{job_id}] Serviço externo falhou: {e}")
        logger.info(f"[{job_id}] Tentando UC local como fallback...")

    # Fallback: UC local
    try:
        from captcha_solver import solve_captcha_with_uc
        return solve_captcha_with_uc(email, password, max_attempts=5, job_id=job_id)
    except Exception as e:
        logger.error(f"[{job_id}] UC local também falhou: {e}")
        return False


def solve_press_and_hold(page, job_id: str, max_attempts: int = 5) -> bool:
    """
    Resolve o CAPTCHA PerimeterX 'Press & Hold' diretamente no Playwright.
    Portado do DARKSAGE — mesma lógica que funciona no criador de hotmail:
    1. Encontra o iframe do CAPTCHA
    2. Entra no iframe, pega coordenadas do #px-captcha
    3. Click-and-hold por 14-20s com micro-movimentos
    4. Verifica se resolveu (URL muda)
    """
    logger.info(f"[{job_id}] CAPTCHA solver: iniciando press-and-hold (max {max_attempts} tentativas)...")
    
    # Passo 0: Clicar "Next/Próximo" na intro page de abuse (se presente)
    try:
        url = page.url.lower()
        if "abuse" in url:
            logger.info(f"[{job_id}] Na página de abuse intro, procurando botão Next...")
            for sel in ["#idSIButton9", "#iNext", "#idBtn_Continue"]:
                try:
                    btn = page.locator(sel)
                    if btn.is_visible(timeout=2000):
                        btn.click(timeout=5000)
                        logger.info(f"[{job_id}] Clicou '{sel}' na intro de abuse")
                        time.sleep(random.uniform(4, 7))
                        break
                except:
                    continue
            else:
                # Tentar por texto
                for text in ["Next", "Próximo", "Avançar", "Continue", "Continuar", "Verify", "Verificar"]:
                    try:
                        btn = page.get_by_role("button", name=text)
                        if btn.is_visible(timeout=1000):
                            btn.click(timeout=5000)
                            logger.info(f"[{job_id}] Clicou botão '{text}' na intro de abuse")
                            time.sleep(random.uniform(4, 7))
                            break
                    except:
                        continue
    except Exception as e:
        logger.warning(f"[{job_id}] Erro ao clicar Next na intro: {e}")
    
    def _check_solved():
        """Verifica se saiu da página de abuse."""
        try:
            url = page.url.lower()
            if "abuse" not in url:
                return True
        except:
            pass
        # Verificar se iframes de captcha sumiram
        try:
            still = page.evaluate("""() => {
                var iframes = document.querySelectorAll('iframe');
                for (var i = 0; i < iframes.length; i++) {
                    var src = (iframes[i].src || '').toLowerCase();
                    if (src.includes('hsprotect') || src.includes('enforcement') || 
                        src.includes('captcha') || src.includes('perimeterx') || src.includes('px-cdn')) {
                        var rect = iframes[i].getBoundingClientRect();
                        if (rect.width > 50 && rect.height > 30) return true;
                    }
                }
                return false;
            }""")
            if not still and "abuse" not in page.url.lower():
                return True
        except:
            pass
        return False
    
    for attempt in range(1, max_attempts + 1):
        logger.info(f"[{job_id}] CAPTCHA tentativa {attempt}/{max_attempts}")
        
        try:
            time.sleep(1)
            if _check_solved():
                logger.info(f"[{job_id}] CAPTCHA já resolvido!")
                return True
            
            # Encontrar o iframe do CAPTCHA
            captcha_iframe = None
            iframe_info = page.evaluate("""() => {
                var iframes = document.querySelectorAll('iframe');
                var results = [];
                for (var i = 0; i < iframes.length; i++) {
                    var src = (iframes[i].src || '').toLowerCase();
                    var rect = iframes[i].getBoundingClientRect();
                    results.push({
                        index: i, src: src.substring(0, 200),
                        x: rect.x, y: rect.y, w: rect.width, h: rect.height
                    });
                }
                return results;
            }""")
            
            logger.info(f"[{job_id}] Iframes encontrados: {len(iframe_info)}")
            
            captcha_idx = None
            captcha_rect = None
            known_srcs = ['hsprotect', 'enforcement', 'captcha', 'perimeterx', 'px-cdn']
            for info in iframe_info:
                logger.info(f"[{job_id}]   iframe[{info['index']}]: src={info['src'][:80]}, size={info['w']:.0f}x{info['h']:.0f}")
                if any(k in info['src'] for k in known_srcs) and info['w'] > 50:
                    captcha_idx = info['index']
                    captcha_rect = info
                    break
            
            if captcha_idx is None:
                # Tentar achar #px-captcha diretamente na página
                try:
                    px_box = page.evaluate("""() => {
                        var el = document.getElementById('px-captcha');
                        if (!el) return null;
                        var r = el.getBoundingClientRect();
                        return {x: r.x, y: r.y, w: r.width, h: r.height};
                    }""")
                    if px_box and px_box['w'] > 10:
                        logger.info(f"[{job_id}] #px-captcha inline encontrado: {px_box}")
                        # Click-and-hold direto no elemento inline
                        cx = px_box['x'] + px_box['w'] / 2
                        cy = px_box['y'] + px_box['h'] / 2
                        
                        hold_dur = random.uniform(14, 20) if attempt <= 3 else random.uniform(18, 24)
                        logger.info(f"[{job_id}] Hold inline ({cx:.0f}, {cy:.0f}) por {hold_dur:.0f}s...")
                        
                        page.mouse.move(cx, cy)
                        time.sleep(random.uniform(0.2, 0.5))
                        page.mouse.down()
                        
                        start = time.time()
                        solved = False
                        while time.time() - start < hold_dur:
                            time.sleep(random.uniform(0.4, 0.9))
                            dx = random.choice([-2, -1, 0, 1, 2])
                            dy = random.choice([-1, 0, 1])
                            try:
                                page.mouse.move(cx + dx, cy + dy)
                            except:
                                pass
                            if _check_solved():
                                solved = True
                                break
                        
                        try:
                            page.mouse.up()
                        except:
                            pass
                        
                        elapsed = time.time() - start
                        logger.info(f"[{job_id}] Solto após {elapsed:.1f}s, solved={solved}")
                        
                        if solved:
                            return True
                        time.sleep(4)
                        if _check_solved():
                            return True
                        time.sleep(random.uniform(2, 4))
                        continue
                except:
                    pass
                
                logger.info(f"[{job_id}] Nenhum iframe/px-captcha encontrado, aguardando...")
                time.sleep(5)
                if _check_solved():
                    return True
                continue
            
            # Scroll iframe pra view
            page.evaluate(f"""() => {{
                var iframes = document.querySelectorAll('iframe');
                if (iframes[{captcha_idx}]) {{
                    iframes[{captcha_idx}].scrollIntoView({{block: 'center'}});
                }}
            }}""")
            time.sleep(0.5)
            
            # Pegar rect atualizado do iframe
            iframe_rect = page.evaluate(f"""() => {{
                var iframes = document.querySelectorAll('iframe');
                var el = iframes[{captcha_idx}];
                if (!el) return null;
                var r = el.getBoundingClientRect();
                return {{x: r.x, y: r.y, w: r.width, h: r.height}};
            }}""")
            
            if not iframe_rect:
                logger.warning(f"[{job_id}] Iframe sumiu após scroll")
                continue
            
            logger.info(f"[{job_id}] iframe rect: x={iframe_rect['x']:.0f} y={iframe_rect['y']:.0f} w={iframe_rect['w']:.0f} h={iframe_rect['h']:.0f}")
            
            # Entrar no iframe pra pegar coordenadas do #px-captcha
            btn_rect = None
            for frame in page.frames:
                frame_url = frame.url.lower()
                if any(k in frame_url for k in known_srcs):
                    try:
                        btn_rect = frame.evaluate("""() => {
                            var el = document.getElementById('px-captcha');
                            if (!el) return null;
                            var r = el.getBoundingClientRect();
                            return {x: r.x, y: r.y, w: r.width, h: r.height};
                        }""")
                        if btn_rect:
                            logger.info(f"[{job_id}] #px-captcha rect dentro do iframe: x={btn_rect['x']:.0f} y={btn_rect['y']:.0f} w={btn_rect['w']:.0f} h={btn_rect['h']:.0f}")
                    except Exception as e:
                        logger.warning(f"[{job_id}] Erro ao ler px-captcha do frame: {e}")
                    break
            
            # Calcular coordenadas absolutas do clique
            if btn_rect and btn_rect['w'] > 10:
                # Coordenadas relativas ao iframe + posição do iframe na página
                click_x = iframe_rect['x'] + btn_rect['x'] + btn_rect['w'] / 2
                click_y = iframe_rect['y'] + btn_rect['y'] + btn_rect['h'] / 2
            else:
                # Fallback: centro do iframe
                click_x = iframe_rect['x'] + iframe_rect['w'] / 2
                click_y = iframe_rect['y'] + iframe_rect['h'] / 2
            
            # Duração variável do hold (como o DARKSAGE)
            hold_dur = random.uniform(14, 20) if attempt <= 3 else random.uniform(18, 24)
            
            logger.info(f"[{job_id}] Press-and-hold em ({click_x:.0f}, {click_y:.0f}) por {hold_dur:.0f}s...")
            
            # === O CORE: click_and_hold com micro-movimentos ===
            # Move pro ponto primeiro
            page.mouse.move(click_x, click_y)
            time.sleep(random.uniform(0.2, 0.5))
            
            # Mouse down (segura)
            page.mouse.down()
            
            start = time.time()
            solved = False
            while time.time() - start < hold_dur:
                time.sleep(random.uniform(0.4, 0.9))
                # Micro-movimento (simula tremor da mão humana, como o DARKSAGE faz)
                dx = random.choice([-2, -1, 0, 1, 2])
                dy = random.choice([-1, 0, 1])
                try:
                    page.mouse.move(click_x + dx, click_y + dy)
                except:
                    pass
                # Checar se resolveu durante o hold
                if _check_solved():
                    solved = True
                    break
            
            # Soltar
            try:
                page.mouse.up()
            except:
                pass
            
            elapsed = time.time() - start
            logger.info(f"[{job_id}] Solto após {elapsed:.1f}s, solved_during_hold={solved}")
            
            if solved:
                logger.info(f"[{job_id}] ✓ CAPTCHA resolvido durante o hold!")
                return True
            
            # Esperar um pouco pra página processar
            time.sleep(4)
            if _check_solved():
                logger.info(f"[{job_id}] ✓ CAPTCHA resolvido após release!")
                return True
            
            # Esperar mais (pode demorar pra redirect)
            for wait_i in range(6):
                time.sleep(5)
                if _check_solved():
                    logger.info(f"[{job_id}] ✓ CAPTCHA resolvido após {(wait_i+1)*5}s!")
                    return True
            
            # Não resolveu, pausa antes de tentar de novo
            time.sleep(random.uniform(2, 5))
        
        except Exception as e:
            logger.error(f"[{job_id}] CAPTCHA solver erro: {str(e)[:200]}")
            time.sleep(3)
            if _check_solved():
                return True
    
    logger.warning(f"[{job_id}] CAPTCHA falhou após {max_attempts} tentativas")
    return False


def solve_abuse_with_uc(email_addr: str, job_id: str, page=None) -> bool:
    """Solve abuse/CAPTCHA. Tries Playwright first (if page given), then UC."""
    # Step 1: Try Playwright solver (faster, no extra browser)
    if page is not None:
        try:
            from captcha_solver import solve_captcha_playwright
            logger.info(f"[{job_id}] Trying Playwright CAPTCHA solver first...")
            if solve_captcha_playwright(page, max_attempts=3, job_id=job_id):
                logger.info(f"[{job_id}] ✓ Playwright CAPTCHA solved!")
                return True
            logger.info(f"[{job_id}] Playwright solver failed, falling back to UC...")
        except Exception as e:
            logger.warning(f"[{job_id}] Playwright solver error: {e}")

    # Step 2: Fall back to undetected-chromedriver
    try:
        from captcha_solver import solve_captcha_with_uc
        logger.info(f"[{job_id}] Solving abuse with UC (max 5 attempts)...")
        return solve_captcha_with_uc(email_addr, HOTMAIL_PASSWORD, max_attempts=5, job_id=job_id)
    except Exception as e:
        logger.error(f"[{job_id}] UC solve error: {e}")
        return False


def search_and_extract(page, service: str, patterns: list, job_id: str, email_addr: str = "") -> dict | None:
    """Navigate to Outlook, search Netflix emails, extract link/code. FAST."""
    _search_deadline = time.time() + 30  # 30s max
    logger.info(f"[{job_id}] Going to Outlook...")
    
    # Tenta navegar pro Outlook — múltiplas URLs de fallback
    current_url = page.url.lower()
    _in_outlook = "outlook.live.com/mail" in current_url and "microsoft-365" not in current_url and "microsoft.com/en" not in current_url
    
    if _in_outlook:
        logger.info(f"[{job_id}] Already in Outlook, skipping navigation")
    else:
        # Tentar múltiplas URLs
        outlook_urls = [
            "https://outlook.live.com/mail/0/",
            "https://outlook.live.com/mail/",
            "https://outlook.live.com/owa/",
            "https://outlook.live.com/mail/0/?nlp=1",
            "https://outlook.live.com/mail/0/?login_hint=" + email_addr,
            "https://outlook.office.com/mail/",
        ]
        for outlook_url in outlook_urls:
            try:
                page.goto(outlook_url, timeout=25000, wait_until="domcontentloaded")
            except:
                pass
            time.sleep(4)
            
            url_check = page.url.lower()
            # Verificar se realmente está no Outlook (não na página de marketing)
            if "outlook.live.com/mail" in url_check and "microsoft-365" not in url_check and "microsoft.com/en" not in url_check:
                logger.info(f"[{job_id}] Outlook OK via {outlook_url}")
                break
            logger.info(f"[{job_id}] {outlook_url} falhou → {url_check}")
        else:
            # Nenhuma URL funcionou — última tentativa: ir pro /mail/ direto do login.live
            logger.warning(f"[{job_id}] Todas URLs do Outlook falharam, tentando via login redirect...")
            try:
                page.goto("https://login.live.com/login.srf?wa=wsignin1.0&rpsnv=167&ct=1733000000&rver=7.5.2237.0&wp=MBI_SSL_SHARED&wreply=https%3a%2f%2foutlook.live.com%2fowa%2f&lc=1046", 
                          timeout=25000, wait_until="domcontentloaded")
                time.sleep(6)
            except:
                pass
    
    # Dismiss any popups/overlays
    page.evaluate("""() => {
        document.querySelectorAll('[role="dialog"], .ms-Overlay, [class*="Overlay"], [class*="DialogSurface"], [class*="backdrop"], [data-portal-node]').forEach(el => el.remove());
    }""")
    for text in ["OK", "Accept", "Got it", "Maybe later", "Skip", "Not now", "Aceitar", "Entendi", "Fechar", "Close", "Dismiss", "No thanks", "Não, obrigado", "Pular"]:
        try:
            btn = page.get_by_role("button", name=text)
            if btn.is_visible(timeout=500):
                btn.click(force=True)
                time.sleep(0.5)
                break
        except:
            continue
    
    url = page.url.lower()
    if "outlook.live.com/mail" not in url or "microsoft-365" in url or "microsoft.com/en" in url:
        logger.error(f"[{job_id}] Not in Outlook: {url}")
        return None
    
    # Determine search term based on service
    SEARCH_TERMS = {
        "password_reset": "from:netflix",
        "household_update": "from:netflix",
        "temp_code": "from:netflix",
        "netflix_disconnect": "from:netflix",
        "prime_code": "from:amazon OR from:primevideo",
        "disney_code": "from:disney",
        "globo_reset": "from:globo OR from:globoplay",
    }
    search_term = SEARCH_TERMS.get(service, "from:netflix")
    search_brand = search_term.replace("from:", "").split(" OR ")[0].strip()
    
    logger.info(f"[{job_id}] Searching emails: {search_term}")
    time.sleep(2)
    
    # Dismiss any dialogs/popups/overlays before searching
    try:
        page.evaluate("""() => {
            document.querySelectorAll('[role="dialog"], .ms-Overlay, [class*="Overlay"], [class*="DialogSurface"], [class*="backdrop"], [data-portal-node]').forEach(el => el.remove());
        }""")
    except:
        pass
    # Also try pressing Escape to close any modal
    try:
        page.keyboard.press("Escape")
        time.sleep(0.5)
    except:
        pass
    
    # Click search or find input
    search_input = None
    try:
        sb = page.locator("button[aria-label*='earch'], button[aria-label*='esquis']").first
        sb.click(timeout=3000)
        time.sleep(1)
    except:
        pass
    
    for sel in ["input[aria-label*='earch']", "input[aria-label*='esquis']",
                 "input[placeholder*='earch']", "input[role='searchbox']", "#topSearchInput"]:
        try:
            si = page.locator(sel).first
            if si.is_visible(timeout=2000):
                search_input = si
                break
        except:
            continue
    
    if search_input:
        # Remove overlays again right before click
        try:
            page.evaluate("""() => {
                document.querySelectorAll('[role="dialog"], [class*="DialogSurface"], [class*="backdrop"], [data-portal-node], .ms-Overlay, [class*="Overlay"]').forEach(el => el.remove());
            }""")
        except:
            pass
        search_input.click(timeout=3000)
        time.sleep(0.3)
        search_input.fill(search_term)
        page.keyboard.press("Enter")
        time.sleep(4)
        
        # If no results, try broader search
        items_check = page.locator("[role='option']").all()
        if len(items_check) == 0:
            logger.info(f"[{job_id}] No results with {search_term}, trying broader search...")
            search_input.fill(search_brand)
            page.keyboard.press("Enter")
            time.sleep(4)

        # Ordenar resultados por Data (mais recente primeiro)
        try:
            sort_btn = page.locator(
                "button[aria-label*='Sort'], button[aria-label*='Classificar'], "
                "button[aria-label*='sort'], button[title*='Sort'], button[title*='Classificar']"
            ).first
            if sort_btn.is_visible(timeout=2000):
                sort_btn.click()
                time.sleep(1)
                # Clicar em "Date" / "Data"
                for label in ["Date", "Data", "Received", "Recebido"]:
                    try:
                        opt = page.get_by_role("menuitem", name=label)
                        if opt.is_visible(timeout=500):
                            opt.click()
                            time.sleep(1.5)
                            logger.info(f"[{job_id}] Sorted by date")
                            break
                    except:
                        continue
        except:
            pass
    else:
        logger.warning(f"[{job_id}] No search input found")
    
    # Find and open matching emails
    email_items = []
    for sel in ["[role='option']", "[data-convid]", "[role='listbox'] [role='option']"]:
        items = page.locator(sel).all()
        if items:
            email_items = items
            break
    
    logger.info(f"[{job_id}] Found {len(email_items)} results")
    
    # Two-pass: first try pattern-matched emails, then any email from the search
    # Também filtra por data — só emails recentes (SEARCH_MINUTES)
    now = datetime.now()
    matched_indices = []
    fallback_indices = []
    email_times = {}  # idx -> hora do email (ex: "6:46 pm")
    NETFLIX_SERVICES = {"password_reset", "household_update", "temp_code", "netflix_disconnect"}
    apply_time_filter = True  # aplica pra todos os serviços

    for idx, item in enumerate(email_items[:15]):
        try:
            text = ((item.text_content() or "") + " " + (item.get_attribute("aria-label") or "")).lower()
            # Filtro de tempo: Outlook mostra hora (ex: "14:32") pra emails de hoje
            # Se mostrar data (ex: "ontem", "seg", "07/04") é antigo — pula
            # Filtro de data REMOVIDO — processa todos os emails

            # Guardar hora do email pra calcular expired depois
            import re as _re2
            time_match = _re2.search(r'(?<!\d)(\d{1,2}:\d{2})\s*(am|pm)?(?!\d)', text, _re2.IGNORECASE)
            if time_match:
                email_times[idx] = time_match.group(0).strip()
                logger.info(f"[{job_id}] Email #{idx} time: {email_times[idx]}")

            if any(p.lower() in text for p in patterns):
                matched_indices.append(idx)
            elif search_brand in text:
                fallback_indices.append(idx)
        except:
            continue
    
    # Process matched first, then fallback (up to 8 total)
    indices_to_check = matched_indices + fallback_indices
    if not indices_to_check:
        # Last resort: try first 5 items regardless
        indices_to_check = list(range(min(5, len(email_items))))
    
    logger.info(f"[{job_id}] Will check {len(matched_indices)} matched + {len(fallback_indices)} fallback emails")
    
    for idx in indices_to_check[:8]:
        if time.time() > _search_deadline:
            logger.warning(f"[{job_id}] Deadline exceeded during email scan")
            return None
        item = email_items[idx]
        try:
            logger.info(f"[{job_id}] Opening email #{idx}...")
            page.evaluate("() => document.querySelectorAll('[role=\"dialog\"], .ms-Overlay').forEach(el => el.remove())")
            
            # Use JS click to avoid Playwright navigation wait issues
            item.evaluate("el => el.click()")
            time.sleep(3)
            
            # Wait for reading pane to load
            for wait_try in range(5):
                body_html = page.evaluate("""() => {
                    for (const sel of ['[role="document"]', '.ReadingPaneContent', 
                        '[aria-label*="message body"]', '[aria-label*="corpo"]', '.wide-content-host']) {
                        const el = document.querySelector(sel);
                        if (el && el.innerHTML.length > 200) return el.innerHTML;
                    }
                    for (const iframe of document.querySelectorAll('iframe')) {
                        try {
                            const doc = iframe.contentDocument || iframe.contentWindow.document;
                            if (doc.body && doc.body.innerHTML.length > 200) return doc.body.innerHTML;
                        } catch(e) {}
                    }
                    return null;
                }""")
                if body_html:
                    break
                time.sleep(1)
            
            if body_html:
                logger.info(f"[{job_id}] Got email body ({len(body_html)} chars)")
                # Debug: save HTML for inspection
                try:
                    with open(f"/tmp/email_body_{job_id}_{idx}.html", "w") as f:
                        f.write(body_html)
                except:
                    pass
                result = extract_netflix_link(body_html, service)
                if result:
                    # Calcular expired baseado na hora do email
                    expired = False
                    time_str = email_times.get(idx, "")
                    if time_str:
                        try:
                            import re as _re3
                            tm = _re3.search(r'(\d{1,2}):(\d{2})\s*(am|pm)?', time_str, _re3.IGNORECASE)
                            if tm:
                                h, m = int(tm.group(1)), int(tm.group(2))
                                ampm = (tm.group(3) or "").lower()
                                if ampm == "pm" and h != 12:
                                    h += 12
                                elif ampm == "am" and h == 12:
                                    h = 0
                                from datetime import datetime as _dt
                                email_dt = _dt.now().replace(hour=h, minute=m, second=0, microsecond=0)
                                age_min = (_dt.now() - email_dt).total_seconds() / 60
                                if age_min < 0:
                                    age_min += 1440  # virou o dia
                                expired = False  # expired check removido
                                logger.info(f"[{job_id}] Email time={time_str}, age={age_min:.0f}min, expired={expired}")
                        except Exception as te:
                            logger.warning(f"[{job_id}] Could not parse email time: {te}")
                    result["expired"] = expired
                    logger.info(f"[{job_id}] FOUND: {result}")
                    return result
                else:
                    logger.info(f"[{job_id}] No link in this email, trying next...")
            else:
                logger.warning(f"[{job_id}] Could not load email body")
        except Exception as e:
            logger.warning(f"[{job_id}] Item error: {e}")
            continue
    
    # Try Junk folder
    if time.time() > _search_deadline:
        logger.warning(f"[{job_id}] search_and_extract deadline exceeded, returning None")
        return None

    logger.info(f"[{job_id}] Checking Junk...")
    try:
        try:
            page.goto("https://outlook.live.com/mail/0/junkemail", timeout=5000, wait_until="domcontentloaded")
        except:
            logger.warning(f"[{job_id}] Junk page load timeout, skipping")
            return None
        time.sleep(2)
        
        for sel in ["[role='option']", "[data-convid]"]:
            items = page.locator(sel).all()
            if items:
                email_items = items
                break
        
        for item in email_items[:10]:
            try:
                text = ((item.text_content() or "") + " " + (item.get_attribute("aria-label") or "")).lower()
                if search_brand not in text:
                    continue
                if not any(p.lower() in text for p in patterns):
                    continue
                item.evaluate("el => el.click()")
                time.sleep(3)
                body_html = page.evaluate("""() => {
                    for (const sel of ['[role="document"]', '.ReadingPaneContent']) {
                        const el = document.querySelector(sel);
                        if (el && el.innerHTML.length > 200) return el.innerHTML;
                    }
                    return null;
                }""")
                if body_html:
                    result = extract_email_content(body_html, service)
                    if result:
                        return result
            except:
                continue
    except:
        pass
    
    return None


def process_job_imap_cached(job_id: str, email_addr: str, service: str, mail) -> bool:
    """Busca email via conexão IMAP já aberta (cache de token). Retorna True se encontrou."""
    import imaplib
    patterns = EMAIL_PATTERNS.get(service, [])
    sender_patterns = IMAP_SENDER_PATTERNS.get(service, [])
    cutoff = (datetime.now() - timedelta(minutes=SEARCH_MINUTES)).strftime("%d-%b-%Y")

    try:
        update_job(job_id, "searching", method="imap", eta=2)
        mail.select("INBOX", readonly=True)

        # Two-pass: subject match first (priority), then fallback
        all_msgs_matched = []
        all_msgs_fallback = []
        
        for sender_hint in sender_patterns[:3]:
            try:
                status, msg_ids = mail.search(None, f'(FROM "{sender_hint}" SINCE "{cutoff}")')
                if status != "OK" or not msg_ids[0]:
                    continue

                for msg_id in reversed(msg_ids[0].split()[-20:]):
                    try:
                        _, msg_data = mail.fetch(msg_id, "(RFC822)")
                        msg = email_lib.message_from_bytes(msg_data[0][1])

                        subject_raw = msg.get("Subject", "")
                        subject = ""
                        for part, enc in decode_header(subject_raw):
                            if isinstance(part, bytes):
                                subject += part.decode(enc or "utf-8", errors="ignore")
                            else:
                                subject += part
                        subject_lower = subject.lower()

                        if any(p.lower() in subject_lower for p in patterns):
                            all_msgs_matched.append(msg)
                        else:
                            all_msgs_fallback.append(msg)
                    except:
                        continue
            except:
                continue
        
        logger.info(f"[{job_id}] IMAP cached: {len(all_msgs_matched)} subject match, {len(all_msgs_fallback)} fallback")
        
        for msg in all_msgs_matched + all_msgs_fallback:
            try:
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() in ("text/plain", "text/html"):
                            payload = part.get_payload(decode=True)
                            if payload:
                                body += payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body += payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")

                result = extract_email_content(body, service)
                if result:
                    expired = False
                    if result.get("link"):
                        update_job(job_id, "found", link=result["link"], method="imap", expired=expired)
                    elif result.get("code"):
                        update_job(job_id, "found", code=result["code"], method="imap", expired=expired)
                    mail.logout()
                    return True
            except:
                continue

        # Tenta também pasta DeletedItems
        try:
            mail.select('"Deleted Items"', readonly=True)
            for sender_hint in sender_patterns[:2]:
                status, msg_ids = mail.search(None, f'(FROM "{sender_hint}" SINCE "{cutoff}")')
                if status == "OK" and msg_ids[0]:
                    for msg_id in reversed(msg_ids[0].split()[-10:]):
                        try:
                            _, msg_data = mail.fetch(msg_id, "(RFC822)")
                            msg = email_lib.message_from_bytes(msg_data[0][1])
                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() in ("text/plain", "text/html"):
                                        payload = part.get_payload(decode=True)
                                        if payload:
                                            body += payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                            else:
                                payload = msg.get_payload(decode=True)
                                if payload:
                                    body += payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
                            result = extract_email_content(body, service)
                            if result:
                                expired = False  # expired check removido
                                if result.get("link"):
                                    update_job(job_id, "found", link=result["link"], method="imap", expired=expired)
                                elif result.get("code"):
                                    update_job(job_id, "found", code=result["code"], method="imap", expired=expired)
                                mail.logout()
                                return True
                        except:
                            continue
        except:
            pass

        mail.logout()
        return False

    except Exception as e:
        logger.error(f"[{job_id}] process_job_imap_cached erro: {e}")
        try:
            mail.logout()
        except:
            pass
        return False


def process_job_api(job_id: str, email_addr: str, service: str) -> bool:
    """Fast API-based extraction — no browser needed. Returns True if successful."""
    import httpx
    
    patterns = EMAIL_PATTERNS.get(service, [])
    
    try:
        update_job(job_id, "connecting", method="api", eta=5)
        
        # === API LOGIN ===
        from api_login import api_login
        login_result = api_login(email_addr, job_id)
        
        if not login_result:
            logger.info(f"[{job_id}] API login failed, will fallback to browser")
            return False
        
        if "error" in login_result:
            err = login_result["error"]
            logger.info(f"[{job_id}] API login: {err}, will fallback to browser")
            if err == "abuse":
                return "abuse"  # sinaliza pra pular code_login e ir direto pro browser
            return False
        
        token = login_result["access_token"]
        cid = login_result["cid"]
        logger.info(f"[{job_id}] API login OK in ~1s")
        
        update_job(job_id, "logged_in", method="api", eta=3)
        
        # === SEARCH ===
        update_job(job_id, "searching", method="api", eta=2)
        
        search_data = httpx.post("https://outlook.live.com/search/api/v2/query?n=124", json={
            "Cvid": "7ef2720e-6e59-ee2b-a217-3a4f427ab0f7",
            "Scenario": {"Name": "owa.react"},
            "TimeZone": "E. South America Standard Time",
            "TextDecorations": "Off",
            "EntityRequests": [{
                "EntityType": "Conversation",
                "ContentSources": ["Exchange"],
                "Filter": {"Or": [
                    {"Term": {"DistinguishedFolderName": "msgfolderroot"}},
                    {"Term": {"DistinguishedFolderName": "DeletedItems"}},
                ]},
                "From": 0,
                "Query": {"QueryString": {"password_reset": "Netflix", "household_update": "Netflix", "temp_code": "Netflix", "netflix_disconnect": "Netflix", "prime_code": "Amazon OR PrimeVideo", "disney_code": "Disney", "globo_reset": "Globo OR Globoplay"}.get(service, "Netflix")},
                "Size": 15,
                "Sort": [
                    {"Field": "Time", "SortDirection": "Desc"},
                ],
                "EnableTopResults": False,
                "TopResultsCount": 0,
            }],
        }, headers={
            "User-Agent": "Outlook-Android/2.0",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "X-AnchorMailbox": f"CID:{cid}",
        }, timeout=30).json()
        
        entity_sets = search_data.get("EntitySets", [])
        results = []
        if entity_sets:
            result_sets = entity_sets[0].get("ResultSets", [{}])
            if result_sets:
                results = result_sets[0].get("Results", [])
        
        logger.info(f"[{job_id}] API search: {len(results)} results")
        
        # Determine brand keywords for sender/topic matching
        BRAND_KEYWORDS = {
            "password_reset": ["netflix"],
            "household_update": ["netflix"],
            "temp_code": ["netflix"],
            "netflix_disconnect": ["netflix"],
            "prime_code": ["amazon", "prime", "primevideo"],
            "disney_code": ["disney", "disneyplus"],
            "globo_reset": ["globo", "globoplay"],
        }
        brand_kws = BRAND_KEYWORDS.get(service, ["netflix"])
        
        if not results:
            update_job(job_id, "not_found",
                message="Nenhum email encontrado. Reenvie a solicitação e tente novamente.")
            return True  # Handled (no fallback needed)
        
        # === GET EMAIL CONTENT ===
        # First pass: only emails matching subject patterns
        # Second pass: any brand email (fallback)
        matching_convs = []
        fallback_convs = []
        for i, conv in enumerate(results[:10]):
            src = conv.get("Source", {})
            topic = src.get("ConversationTopic", "").lower()
            sender = src.get("SenderSMTPAddress", "").lower()
            
            if any(p in topic for p in patterns):
                matching_convs.append(conv)
            elif any(kw in sender or kw in topic for kw in brand_kws):
                fallback_convs.append(conv)
        
        logger.info(f"[{job_id}] API: {len(matching_convs)} matching, {len(fallback_convs)} fallback")
        
        for conv in matching_convs + fallback_convs:
            src = conv.get("Source", {})
            topic = src.get("ConversationTopic", "").lower()
            
            # Get all item IDs in this conversation — inverte pra pegar o mais recente primeiro
            item_ids = src.get("GlobalItemIds", src.get("ItemIds", []))
            if not item_ids:
                item_id_obj = src.get("ItemId", {})
                if item_id_obj:
                    item_ids = [item_id_obj]
            item_ids = list(reversed(item_ids))  # mais recente primeiro
            
            for item_obj in item_ids[:3]:
                item_id = item_obj.get("Id", "")
                if not item_id:
                    continue
                
                try:
                    r = httpx.post("https://outlook.live.com/owa/service.svc?action=GetItem", json={
                        "__type": "GetItemJsonRequest:#Exchange",
                        "Header": {
                            "__type": "JsonRequestHeaders:#Exchange",
                            "RequestServerVersion": "V2018_01_08",
                        },
                        "Body": {
                            "__type": "GetItemRequest:#Exchange",
                            "ItemShape": {
                                "__type": "ItemResponseShape:#Exchange",
                                "BaseShape": "Default",
                                "BodyType": "HTML",
                                "FilterHtmlContent": False,
                                "AdditionalProperties": [
                                    {"__type": "PropertyUri:#Exchange", "FieldURI": "item:Body"},
                                    {"__type": "PropertyUri:#Exchange", "FieldURI": "item:Subject"},
                                    {"__type": "PropertyUri:#Exchange", "FieldURI": "item:DateTimeReceived"},
                                ]
                            },
                            "ItemIds": [
                                {"__type": "ItemId:#Exchange", "Id": item_id}
                            ],
                        },
                    }, headers={
                        "User-Agent": "Outlook-Android/2.0",
                        "Authorization": f"Bearer {token}",
                        "X-AnchorMailbox": f"CID:{cid}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Action": "GetItem",
                    }, timeout=30, follow_redirects=False)
                    
                    data = r.json()
                    items = data.get("Body", {}).get("ResponseMessages", {}).get("Items", [])
                    if items:
                        msg = items[0].get("Items", [{}])[0]
                        body_html = msg.get("Body", {}).get("Value", "")
                        subject = msg.get("Subject", "")
                        received = msg.get("DateTimeReceived", "") or msg.get("DateTimeSent", "") or ""

                        # Filtra emails mais antigos que SEARCH_MINUTES
                        if received:
                            try:
                                from datetime import timezone
                                recv_dt = datetime.fromisoformat(received.replace("Z", "+00:00"))
                                age_minutes = (datetime.now(timezone.utc) - recv_dt).total_seconds() / 60
                                if age_minutes > SEARCH_MINUTES:
                                    logger.info(f"[{job_id}] API skip email antigo ({age_minutes:.0f}min): '{subject}'")
                                    continue
                            except:
                                pass  # Se não conseguir parsear a data, processa mesmo assim

                        logger.info(f"[{job_id}] API email #{i}: '{subject}' ({len(body_html)} chars)")
                        
                        if body_html:
                            result = extract_email_content(body_html, service)
                            if result:
                                # Check if email is close to expiring (>12 min = warn)
                                expired = False
                                if received:
                                    try:
                                        from datetime import timezone as tz
                                        recv_dt = datetime.fromisoformat(received.replace("Z", "+00:00"))
                                        age_min = (datetime.now(tz.utc) - recv_dt).total_seconds() / 60
                                        expired = False  # expired check removido
                                    except:
                                        pass
                                logger.info(f"[{job_id}] API FOUND: {result} (expired={expired})")
                                update_job(job_id, "found",
                                    link=result.get("link"), code=result.get("code"),
                                    method="api", expired=expired)
                                return True
                except Exception as e:
                    logger.error(f"[{job_id}] API GetItem error: {e}")
                    continue
        
        update_job(job_id, "not_found",
            message="Nenhum email encontrado com o conteúdo esperado. Reenvie a solicitação e tente novamente.")
        return True  # Handled
        
    except Exception as e:
        logger.error(f"[{job_id}] API error: {traceback.format_exc()}")
        return False


def gmail_login(page, email_addr: str, password: str, job_id: str) -> bool:
    """Login to Gmail via browser. Returns True if successful."""
    logger.info(f"[{job_id}] Gmail login: {email_addr}")
    
    try:
        page.goto("https://accounts.google.com/signin/v2/identifier?service=mail&flowName=GlifWebSignIn", 
                   timeout=20000, wait_until="domcontentloaded")
        time.sleep(2)
        
        # Email field
        email_input = page.locator("input[type=email]")
        email_input.wait_for(timeout=10000)
        email_input.fill(email_addr)
        page.keyboard.press("Enter")
        time.sleep(3)

        # Pode aparecer tela de "escolha uma conta" ou "confirme identidade"
        # Tenta clicar em botões de continuar/próximo antes da senha
        for _ in range(3):
            url_now = page.url.lower()
            body_now = ""
            try:
                body_now = page.inner_text("body").lower()
            except:
                pass

            # Se já apareceu campo de senha, para
            if page.locator("input[type=password]").is_visible():
                break

            # Se apareceu lista de contas, clica no email certo
            try:
                acct = page.get_by_text(email_addr, exact=False)
                if acct.is_visible(timeout=1000):
                    acct.click()
                    logger.info(f"[{job_id}] Gmail: selecionou conta na lista")
                    time.sleep(2)
                    continue
            except:
                pass

            # Tenta clicar em Next/Próximo/Continuar
            clicked = False
            for txt in ["Next", "Próximo", "Continue", "Continuar"]:
                try:
                    btn = page.get_by_role("button", name=txt)
                    if btn.is_visible(timeout=800):
                        btn.click()
                        clicked = True
                        logger.info(f"[{job_id}] Gmail: clicou '{txt}'")
                        time.sleep(2)
                        break
                except:
                    continue

            if not clicked:
                break

        # Password field
        try:
            pwd_input = page.locator("input[type=password]")
            pwd_input.wait_for(timeout=12000)
            pwd_input.fill(password)
            page.keyboard.press("Enter")
            time.sleep(4)
        except Exception as e:
            # Tira screenshot pra debug
            try:
                page.screenshot(path=f"/tmp/gmail_fail_{job_id}.png")
            except:
                pass
            logger.error(f"[{job_id}] Gmail: password field not found: {e}")
            logger.info(f"[{job_id}] Gmail: url={page.url}")
            return False
        
        # Check result
        url = page.url.lower()
        body = page.inner_text("body").lower()[:300]
        
        if "wrong password" in body or "senha incorreta" in body or "incorrect" in body:
            logger.error(f"[{job_id}] Gmail: wrong password")
            return False
        
        if "challenge" in url or "signin/v2/challenge" in url:
            logger.warning(f"[{job_id}] Gmail: security challenge required")
            # Try to handle phone/recovery challenges
            time.sleep(3)
            # Check if it's asking for phone or recovery email
            if "phone" in body or "telefone" in body:
                logger.error(f"[{job_id}] Gmail: phone verification needed — can't handle")
                return False
        
        # Check if we landed on Gmail or myaccount
        if "mail.google" in url or "inbox" in url or "myaccount" in url or "#" in url:
            logger.info(f"[{job_id}] Gmail login OK!")
            return True
        
        # Sometimes Google shows "confirm recovery email" or other prompts
        # Try clicking "Not now" or "Next" buttons
        for skip_text in ["Not now", "Agora não", "Skip", "Pular", "Next", "Próximo"]:
            try:
                btn = page.get_by_text(skip_text, exact=False)
                if btn.is_visible(timeout=1500):
                    btn.click()
                    logger.info(f"[{job_id}] Gmail: clicked '{skip_text}'")
                    time.sleep(2)
                    break
            except:
                continue
        
        url = page.url.lower()
        if "mail.google" in url or "inbox" in url or "myaccount" in url:
            logger.info(f"[{job_id}] Gmail login OK (after skip)!")
            return True
        
        logger.info(f"[{job_id}] Gmail: post-login url={url}")
        return True  # Assume OK if no error
        
    except Exception as e:
        logger.error(f"[{job_id}] Gmail login error: {e}")
        return False


def gmail_search_and_extract(page, service: str, patterns: list, job_id: str) -> dict | None:
    """Search Gmail for emails and extract links/codes."""
    
    GMAIL_SEARCH_TERMS = {
        "password_reset": "from:netflix subject:(redefinição OR reset OR password)",
        "household_update": "from:netflix subject:(residência OR household)",
        "temp_code": "from:netflix subject:(código OR code OR temporário OR temporary)",
        "netflix_disconnect": "from:netflix subject:(desconectar OR disconnect OR sign out)",
        "prime_code": "from:(amazon OR primevideo) subject:(código OR code OR verification)",
        "disney_code": "from:disney subject:(código OR code OR verification)",
        "globo_reset": "from:(globo OR globoplay) subject:(redefinição OR reset OR senha OR password OR código OR code)",
    }
    
    search_term = GMAIL_SEARCH_TERMS.get(service, "from:netflix")
    
    # Go to Gmail
    page.goto("https://mail.google.com/mail/u/0/#search/" + search_term.replace(" ", "+"),
              timeout=20000, wait_until="domcontentloaded")
    time.sleep(5)
    
    logger.info(f"[{job_id}] Gmail: searching '{search_term}'")
    
    # Wait for email list to load
    time.sleep(3)
    
    # Find email rows
    email_rows = page.locator("tr.zA").all()
    if not email_rows:
        # Try alternative selectors
        email_rows = page.locator("[role='row'][jscontroller]").all()
    
    logger.info(f"[{job_id}] Gmail: found {len(email_rows)} results")
    
    if not email_rows:
        # Maybe no results, check
        body = page.inner_text("body").lower()
        if "no results" in body or "nenhum resultado" in body:
            logger.info(f"[{job_id}] Gmail: no search results")
            return None
        # Try broader search
        page.goto("https://mail.google.com/mail/u/0/#inbox", timeout=15000, wait_until="domcontentloaded")
        time.sleep(4)
        email_rows = page.locator("tr.zA").all()
        logger.info(f"[{job_id}] Gmail: inbox has {len(email_rows)} emails")
    
    # Check emails (matched first, then fallback)
    matched = []
    fallback = []
    for idx, row in enumerate(email_rows[:15]):
        try:
            text = (row.text_content() or "").lower()
            if any(p.lower() in text for p in patterns):
                matched.append(idx)
            else:
                fallback.append(idx)
        except:
            continue
    
    indices = matched + fallback
    if not indices:
        indices = list(range(min(5, len(email_rows))))
    
    logger.info(f"[{job_id}] Gmail: {len(matched)} matched + {len(fallback)} fallback")
    
    for idx in indices[:8]:
        try:
            row = email_rows[idx]
            logger.info(f"[{job_id}] Gmail: opening email #{idx}...")
            row.click()
            time.sleep(3)
            
            # Get email body
            body_html = page.evaluate("""() => {
                // Gmail email body
                const selectors = ['.a3s.aiL', '.ii.gt', '[role="listitem"] .a3s', '.gs .ii'];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerHTML.length > 100) return el.innerHTML;
                }
                // Fallback: any large content div
                const divs = document.querySelectorAll('div[dir="ltr"], div.a3s');
                for (const div of divs) {
                    if (div.innerHTML.length > 200) return div.innerHTML;
                }
                return null;
            }""")
            
            if body_html:
                logger.info(f"[{job_id}] Gmail: got email body ({len(body_html)} chars)")
                result = extract_email_content(body_html, service)
                if result:
                    logger.info(f"[{job_id}] Gmail: FOUND: {result}")
                    return result
                else:
                    logger.info(f"[{job_id}] Gmail: no link in this email, trying next...")
            else:
                logger.warning(f"[{job_id}] Gmail: could not load email body")
            
            # Go back to search results
            page.keyboard.press("u")  # Gmail shortcut: back to list
            time.sleep(2)
            
            # Re-fetch rows after navigating back
            email_rows = page.locator("tr.zA").all()
            
        except Exception as e:
            logger.warning(f"[{job_id}] Gmail: error on email #{idx}: {e}")
            try:
                page.keyboard.press("u")
                time.sleep(2)
                email_rows = page.locator("tr.zA").all()
            except:
                pass
            continue
    
    return None


def process_job_gmail_imap(job_id: str, email_addr: str, service: str, app_password: str):
    """Busca emails do Gmail via IMAP com senha de app. Rápido, sem browser."""
    patterns = EMAIL_PATTERNS.get(service, [])
    sender_keywords = IMAP_SENDER_PATTERNS.get(service, [])

    try:
        update_job(job_id, "connecting", method="imap", eta=5)
        logger.info(f"[{job_id}] Gmail IMAP: conectando como {email_addr}...")

        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=15)
        mail.login(email_addr, app_password)
        mail.select("INBOX", readonly=True)

        update_job(job_id, "searching", method="imap", eta=3)

        cutoff = (datetime.now() - timedelta(minutes=SEARCH_MINUTES)).strftime("%d-%b-%Y")
        status, msg_ids = mail.search(None, f'(SINCE "{cutoff}")')

        if status != "OK" or not msg_ids[0]:
            # Tenta últimas 24h
            cutoff2 = (datetime.now() - timedelta(hours=24)).strftime("%d-%b-%Y")
            status, msg_ids = mail.search(None, f'(SINCE "{cutoff2}")')

        if status != "OK" or not msg_ids[0]:
            mail.logout()
            update_job(job_id, "not_found", message="Nenhum email encontrado. Reenvie a solicitação e tente novamente.")
            return

        all_ids = msg_ids[0].split()
        logger.info(f"[{job_id}] Gmail IMAP: {len(all_ids)} emails recentes")

        # Two-pass: subject match first (priority), then fallback
        subject_matched_ids = []
        fallback_ids = []
        
        for msg_id in reversed(all_ids[-20:]):
            try:
                _, hdr_data = mail.fetch(msg_id, "(BODY[HEADER.FIELDS (FROM SUBJECT)])")
                header_msg = email_lib.message_from_bytes(hdr_data[0][1])

                from_header = (header_msg.get("From", "") or "").lower()
                if sender_keywords and not any(kw in from_header for kw in sender_keywords):
                    continue

                subject_raw = header_msg.get("Subject", "") or ""
                subject = ""
                try:
                    for part_bytes, charset in decode_header(subject_raw):
                        if isinstance(part_bytes, bytes):
                            subject += part_bytes.decode(charset or "utf-8", errors="ignore")
                        else:
                            subject += str(part_bytes)
                except:
                    subject = subject_raw
                subject = subject.lower()

                if patterns and any(p in subject for p in patterns):
                    subject_matched_ids.append(msg_id)
                else:
                    fallback_ids.append(msg_id)
            except:
                continue
        
        logger.info(f"[{job_id}] Gmail IMAP: {len(subject_matched_ids)} subject match, {len(fallback_ids)} fallback")
        
        for msg_id in subject_matched_ids + fallback_ids:
            try:
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                msg = email_lib.message_from_bytes(msg_data[0][1])

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() in ("text/html", "text/plain"):
                            payload = part.get_payload(decode=True)
                            if payload:
                                body += payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body += payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")

                if not body:
                    continue

                result = extract_email_content(body, service)
                if result:
                    expired = False  # expired check removido
                    logger.info(f"[{job_id}] Gmail IMAP FOUND: {result} (expired={expired})")
                    mail.logout()
                    update_job(job_id, "found", link=result.get("link"), code=result.get("code"), method="imap", expired=expired)
                    return

            except Exception as e:
                logger.warning(f"[{job_id}] Gmail IMAP msg error: {e}")
                continue

        mail.logout()
        update_job(job_id, "not_found", message="Nenhum email encontrado nos últimos 15 minutos. Reenvie e tente novamente.")

    except Exception as e:
        logger.error(f"[{job_id}] Gmail IMAP error: {traceback.format_exc()}")
        update_job(job_id, "error", message=f"Erro Gmail IMAP: {str(e)[:80]}")


def process_job_gmail(job_id: str, email_addr: str, service: str, password: str):
    """Process job by logging into Gmail directly."""
    from playwright.sync_api import sync_playwright
    
    patterns = EMAIL_PATTERNS.get(service, [])
    pw = None
    browser = None
    
    try:
        update_job(job_id, "connecting", method="playwright", eta=30,
                   message="Conectando ao Gmail...")
        
        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=_should_use_headless(),
            channel="chrome",
            args=["--no-sandbox", "--disable-dev-shm-usage",
                   "--disable-blink-features=AutomationControlled"]
        )
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        from playwright_stealth import Stealth
        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)
        
        # Login
        ok = gmail_login(page, email_addr, password, job_id)
        if not ok:
            update_job(job_id, "error", 
                       message="Login Gmail falhou. Verifique email e senha.")
            return
        
        update_job(job_id, "searching", method="playwright", eta=15,
                   message="Buscando emails...")
        
        # Search
        result = gmail_search_and_extract(page, service, patterns, job_id)
        
        if result:
            update_job(job_id, "found",
                       link=result.get("link"),
                       code=result.get("code"),
                       method="playwright", expired=result.get("expired", False))
        else:
            update_job(job_id, "not_found",
                       message="Nenhum email encontrado. Verifique se o email foi solicitado.")
    
    except Exception as e:
        logger.error(f"[{job_id}] Gmail job error: {traceback.format_exc()}")
        update_job(job_id, "error", message=f"Erro: {str(e)[:100]}")
    
    finally:
        if browser:
            try:
                browser.close()
            except:
                pass
        if pw:
            try:
                pw.stop()
            except:
                pass


RECOVERY_FALLBACKS = (
    ["netflix@cinepremiu.com"]
    + [f"netflix{i}@cinepremiu.com" for i in range(1, 20)]
    + [f"{i}netflix@cinepremiu.com" for i in range(1, 20)]
)


def _get_recovery_candidates(email_addr: str, masked_prefix: str) -> list:
    """Build ordered list of recovery email candidates for code login.
    Most accounts: {username}@cinepremiu.com
    Some accounts: netflix@cinepremiu.com or netflix1@cinepremiu.com
    Some accounts: tech34011@gmail.com (forwards to cinepremiu)
    """
    username = email_addr.split("@")[0].lower()
    candidates = []
    # 1. Always try username@cinepremiu.com first
    candidates.append(f"{username}@cinepremiu.com")
    # 2. Check KNOWN_RECOVERY_EMAILS that match the masked prefix (includes @gmail.com etc)
    if masked_prefix:
        prefix_lower = masked_prefix.lower()
        for known in KNOWN_RECOVERY_EMAILS:
            local = known.split("@")[0].replace(".", "")
            if local.startswith(prefix_lower.replace(".", "")) and known not in candidates:
                candidates.append(known)
    # 3. Fallbacks that match the masked prefix MS shows
    for fb in RECOVERY_FALLBACKS:
        local = fb.split("@")[0]
        if local.startswith(masked_prefix.lower()) and fb not in candidates:
            candidates.append(fb)
    # 4. Remaining fallbacks (even if prefix doesn't match — MS might truncate oddly)
    for fb in RECOVERY_FALLBACKS:
        if fb not in candidates:
            candidates.append(fb)
    return candidates


def _imap_get_max_id() -> int:
    """Get the highest IMAP message ID to detect new emails after this point."""
    try:
        mail = imaplib.IMAP4_SSL(RECOVERY_IMAP_SERVER, 993, timeout=10)
        mail.login(RECOVERY_EMAIL, RECOVERY_PASSWORD)
        mail.select("INBOX", readonly=True)
        status, ids = mail.search(None, "ALL")
        mail.logout()
        if status == "OK" and ids[0]:
            return max(int(i) for i in ids[0].split())
        return 0
    except:
        return 0


def _gmail_imap_get_code(gmail_addr: str, min_id: int, max_wait: int = 120) -> str | None:
    """Read MS verification code directly from Gmail IMAP (faster than forwarding).
    Uses timestamp-based filtering: only accepts the NEWEST MS email received after we clicked Send.
    """
    # Normalize: tech.34011@gmail.com -> tech34011@gmail.com for IMAP lookup
    local = gmail_addr.split("@")[0].replace(".", "")
    canonical = f"{local}@gmail.com"
    app_pass = GMAIL_IMAP_ACCOUNTS.get(canonical)
    if not app_pass:
        app_pass = GMAIL_IMAP_ACCOUNTS.get(gmail_addr)
    if not app_pass:
        return None

    # Record the time we started waiting (code was just sent by MS)
    send_time = time.time()
    logger.info(f"Reading code directly from Gmail IMAP: {canonical} (min_id>{min_id})")
    start = time.time()
    seen_codes = set()

    while time.time() - start < max_wait:
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=15)
            mail.login(canonical, app_pass)
            mail.select("INBOX", readonly=True)

            cutoff = (datetime.now() - timedelta(minutes=5)).strftime("%d-%b-%Y")
            q = f'(FROM "microsoft" SINCE "{cutoff}")'
            status, ids = mail.search(None, q)

            if status == "OK" and ids[0]:
                # Check newest first
                for mid_bytes in reversed(ids[0].split()[-10:]):
                    mid_int = int(mid_bytes)
                    if mid_int <= min_id:
                        continue

                    try:
                        _, data = mail.fetch(mid_bytes, "(RFC822)")
                        msg = email_lib.message_from_bytes(data[0][1])
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() in ("text/plain", "text/html"):
                                    p = part.get_payload(decode=True)
                                    if p:
                                        body += p.decode(part.get_content_charset() or "utf-8", errors="ignore")
                        else:
                            p = msg.get_payload(decode=True)
                            if p:
                                body += p.decode(msg.get_content_charset() or "utf-8", errors="ignore")

                        for pat in [
                            r'código de uso único é:\s*(\d{4,8})',
                            r'one-time code is:\s*(\d{4,8})',
                            r'código de segurança[:\s]+(\d{4,8})',
                            r'security code[:\s]+(\d{4,8})',
                            r'>\s*(\d{6,8})\s*<',
                            r'(?:code|código)[:\s]*(\d{6})',
                        ]:
                            m = re.findall(pat, body, re.IGNORECASE)
                            if m:
                                code = m[0].strip()
                                logger.info(f"GOT CODE from Gmail: {code} (id={mid_int})")
                                mail.logout()
                                return code
                    except:
                        continue

                # Also try: if no new ID found, grab the NEWEST email regardless of min_id
                # (in case Gmail reused the ID or search was delayed)
                newest_mid = ids[0].split()[-1]
                newest_int = int(newest_mid)
                if newest_int not in seen_codes:
                    seen_codes.add(newest_int)
                    try:
                        _, data = mail.fetch(newest_mid, "(RFC822)")
                        msg = email_lib.message_from_bytes(data[0][1])
                        # Check if this email was received recently (within 3 min of send_time)
                        date_str = msg.get("Date", "")
                        from email.utils import parsedate_to_datetime
                        try:
                            email_dt = parsedate_to_datetime(date_str)
                            email_ts = email_dt.timestamp()
                            # Only accept if email arrived after we started waiting (with 30s grace)
                            if email_ts >= send_time - 30:
                                body = ""
                                if msg.is_multipart():
                                    for part in msg.walk():
                                        if part.get_content_type() in ("text/plain", "text/html"):
                                            p = part.get_payload(decode=True)
                                            if p:
                                                body += p.decode(part.get_content_charset() or "utf-8", errors="ignore")
                                else:
                                    p = msg.get_payload(decode=True)
                                    if p:
                                        body += p.decode(msg.get_content_charset() or "utf-8", errors="ignore")

                                for pat in [
                                    r'código de uso único é:\s*(\d{4,8})',
                                    r'one-time code is:\s*(\d{4,8})',
                                    r'código de segurança[:\s]+(\d{4,8})',
                                    r'security code[:\s]+(\d{4,8})',
                                    r'>\s*(\d{6,8})\s*<',
                                    r'(?:code|código)[:\s]*(\d{6})',
                                ]:
                                    m = re.findall(pat, body, re.IGNORECASE)
                                    if m:
                                        code = m[0].strip()
                                        logger.info(f"GOT CODE from Gmail (newest fallback): {code}")
                                        mail.logout()
                                        return code
                        except:
                            pass
                    except:
                        pass

            mail.logout()
        except Exception as e:
            logger.warning(f"Gmail IMAP err: {e}")

        elapsed = int(time.time() - start)
        logger.info(f"... waiting Gmail {elapsed}s")
        time.sleep(3)

    return None


def _gmail_get_max_id(gmail_addr: str) -> int:
    """Get highest IMAP ID from Gmail inbox."""
    local = gmail_addr.split("@")[0].replace(".", "")
    canonical = f"{local}@gmail.com"
    app_pass = GMAIL_IMAP_ACCOUNTS.get(canonical) or GMAIL_IMAP_ACCOUNTS.get(gmail_addr)
    if not app_pass:
        return 0
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=10)
        mail.login(canonical, app_pass)
        mail.select("INBOX", readonly=True)
        status, ids = mail.search(None, "ALL")
        mail.logout()
        if status == "OK" and ids[0]:
            return max(int(i) for i in ids[0].split())
        return 0
    except:
        return 0


def _imap_get_new_code(min_id: int, target_to: str = "", max_wait: int = 120) -> str | None:
    """Get MS verification code from IMAP, only from messages with ID > min_id."""
    logger.info(f"Waiting for new code (min_id>{min_id}, to={target_to}, max={max_wait}s)")
    start = time.time()

    while time.time() - start < max_wait:
        try:
            mail = imaplib.IMAP4_SSL(RECOVERY_IMAP_SERVER, 993, timeout=10)
            mail.login(RECOVERY_EMAIL, RECOVERY_PASSWORD)
            mail.select("INBOX", readonly=True)

            # Search for recent MS emails
            cutoff = (datetime.now() - timedelta(minutes=10)).strftime("%d-%b-%Y")
            if target_to:
                q = f'(FROM "microsoft" TO "{target_to}" SINCE "{cutoff}")'
            else:
                q = f'(FROM "microsoft" SINCE "{cutoff}")'
            status, ids = mail.search(None, q)

            if status == "OK" and ids[0]:
                for mid_bytes in reversed(ids[0].split()):
                    mid_int = int(mid_bytes)
                    if mid_int <= min_id:
                        continue  # skip old

                    try:
                        _, data = mail.fetch(mid_bytes, "(RFC822)")
                        msg = email_lib.message_from_bytes(data[0][1])
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() in ("text/plain", "text/html"):
                                    p = part.get_payload(decode=True)
                                    if p:
                                        body += p.decode(part.get_content_charset() or "utf-8", errors="ignore")
                        else:
                            p = msg.get_payload(decode=True)
                            if p:
                                body += p.decode(msg.get_content_charset() or "utf-8", errors="ignore")

                        for pat in [
                            r'código de uso único é:\s*(\d{4,8})',
                            r'one-time code is:\s*(\d{4,8})',
                            r'código de segurança[:\s]+(\d{4,8})',
                            r'security code[:\s]+(\d{4,8})',
                            r'>\s*(\d{6,8})\s*<',
                            r'(?:code|código)[:\s]*(\d{6})',
                        ]:
                            m = re.findall(pat, body, re.IGNORECASE)
                            if m:
                                code = m[0].strip()
                                to_h = (msg.get("To", "") or "")[:50]
                                logger.info(f"GOT CODE: {code} (to: {to_h})")
                                mail.logout()
                                return code
                    except:
                        continue

            mail.logout()
        except Exception as e:
            logger.warning(f"IMAP err: {e}")

        elapsed = int(time.time() - start)
        logger.info(f"... waiting {elapsed}s")
        time.sleep(5)

    return None


def process_job_code_login(job_id: str, email_addr: str, service: str) -> bool:
    """
    Login to Hotmail via verification code sent to @cinepremiu.com recovery email.
    Used when password login fails.
    Returns True if handled (success or definitive failure), False to try other methods.
    """
    from playwright.sync_api import sync_playwright

    patterns = EMAIL_PATTERNS.get(service, [])
    pw = None
    browser = None

    try:
        update_job(job_id, "connecting", method="code", eta=60,
                   message="Login por código... aguarde ~1min")

        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=_should_use_headless(), channel="chrome",
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"]
        )
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        )
        try:
            from playwright_stealth import Stealth
            page = ctx.new_page()
            Stealth().apply_stealth_sync(page)
        except:
            page = ctx.new_page()

        # === STEP 1: Go to login, enter email ===
        page.goto("https://login.live.com/", timeout=20000, wait_until="domcontentloaded")
        time.sleep(2)
        page.fill("input[type=email]", email_addr)
        page.keyboard.press("Enter")
        time.sleep(4)

        body = page.inner_text("body").lower()
        has_send_code = "send code" in body or "enviar código" in body

        if not has_send_code:
            logger.info(f"[{job_id}] Code login: not on code page, aborting")
            return False  # Let other methods try

        # === STEP 2: Get masked prefix, build candidates ===
        masked = re.search(r'(\w{1,10})\*+@', body)
        prefix = masked.group(1) if masked else ""
        candidates = _get_recovery_candidates(email_addr, prefix)
        logger.info(f"[{job_id}] Code login: hint={prefix}***, candidates={candidates}")

        # === STEP 3: Try each recovery email ===
        code_obtained = False
        for recovery in candidates:
            logger.info(f"[{job_id}] Trying recovery: {recovery}")

            # Check if this is a Gmail with direct IMAP access
            _recovery_canonical = recovery.split("@")[0].replace(".", "") + "@gmail.com" if "@gmail.com" in recovery else ""
            _use_gmail_direct = bool(_recovery_canonical and (
                GMAIL_IMAP_ACCOUNTS.get(_recovery_canonical) or GMAIL_IMAP_ACCOUNTS.get(recovery)
            ))

            # Snapshot IMAP max ID before sending
            if _use_gmail_direct:
                max_id_before = _gmail_get_max_id(recovery)
                logger.info(f"[{job_id}] Will read code from Gmail IMAP directly")
            else:
                max_id_before = _imap_get_max_id()

            inp = page.locator("#proof-confirmation-email-input")
            if not inp.is_visible(timeout=2000):
                inp = page.locator("input[type=text]").first
            inp.fill("")
            time.sleep(0.2)
            inp.fill(recovery)
            time.sleep(0.3)

            for txt in ["Send code", "Enviar código"]:
                try:
                    btn = page.get_by_role("button", name=txt)
                    if btn.is_visible(timeout=1500):
                        btn.click()
                        logger.info(f"[{job_id}] Clicked: {txt}")
                        break
                except:
                    pass

            time.sleep(3)
            nb = page.inner_text("body").lower()

            if "doesn't match" in nb or "não corresponde" in nb:
                logger.info(f"[{job_id}] Wrong recovery: {recovery}")
                continue

            # Code was sent!
            logger.info(f"[{job_id}] Code sent to {recovery}! Reading from IMAP...")
            update_job(job_id, "connecting", method="code", eta=45,
                       message="Código enviado, aguardando email...")

            if _use_gmail_direct:
                # Read directly from Gmail — much faster than waiting for forwarding
                code = _gmail_imap_get_code(recovery, min_id=max_id_before, max_wait=120)
            else:
                code = _imap_get_new_code(min_id=max_id_before, target_to=recovery, max_wait=120)
                if not code:
                    # Broad search (catchall might receive with different TO)
                    code = _imap_get_new_code(min_id=max_id_before, target_to="", max_wait=30)

            if code:
                logger.info(f"[{job_id}] Got code: {code}")
                code_obtained = True

                # Type code in split boxes
                first_box = page.locator("#codeEntry-0")
                if first_box.is_visible(timeout=3000):
                    first_box.click()
                    time.sleep(0.2)
                    for digit in code:
                        page.keyboard.type(digit)
                        time.sleep(0.15)
                else:
                    # Fallback: find any visible input
                    for sel in ["input[type=text]", "input[type=tel]"]:
                        try:
                            i = page.locator(sel).first
                            if i.is_visible(timeout=1000):
                                i.click()
                                for digit in code:
                                    page.keyboard.type(digit)
                                    time.sleep(0.15)
                                break
                        except:
                            pass

                time.sleep(5)

                cb = page.inner_text("body").lower()
                if "incorrect" in cb or "incorreto" in cb:
                    logger.warning(f"[{job_id}] Code rejected, might be expired")
                    # Try sending again with fresh code
                    max_id_before2 = _imap_get_max_id()
                    for txt in ["Send code", "Enviar código"]:
                        try:
                            btn = page.get_by_role("button", name=txt)
                            if btn.is_visible(timeout=2000):
                                btn.click()
                                break
                        except:
                            pass
                    time.sleep(2)
                    code2 = _imap_get_new_code(min_id=max_id_before2, target_to=recovery, max_wait=90)
                    if code2:
                        logger.info(f"[{job_id}] Retry code: {code2}")
                        for j in range(6):
                            try:
                                page.locator(f"#codeEntry-{j}").fill("")
                            except:
                                pass
                        time.sleep(0.3)
                        first_box = page.locator("#codeEntry-0")
                        if first_box.is_visible(timeout=2000):
                            first_box.click()
                            time.sleep(0.2)
                            for digit in code2:
                                page.keyboard.type(digit)
                                time.sleep(0.15)
                        time.sleep(5)
                        cb2 = page.inner_text("body").lower()
                        if "incorrect" in cb2 or "incorreto" in cb2:
                            logger.error(f"[{job_id}] Second code also rejected")
                            update_job(job_id, "error",
                                       message="Código rejeitado. Tente novamente em alguns minutos.")
                            return True
                    else:
                        update_job(job_id, "error",
                                   message="Código expirado e novo não chegou.")
                        return True
                break
            else:
                logger.warning(f"[{job_id}] Code not received for {recovery}")
                continue

        if not code_obtained:
            logger.error(f"[{job_id}] Code login failed: no code received from any candidate")
            return False  # Let other methods try

        # === STEP 4: Post-login (stay signed in, etc.) ===
        logger.info(f"[{job_id}] Code accepted, handling post-login...")
        # Tenta pular prompt de segurança primeiro
        _try_skip_security_prompt(page, job_id)
        for _ in range(8):
            url = page.url.lower()
            if "outlook.live.com" in url:
                break
            # Tenta pular security prompt a cada iteração
            if _try_skip_security_prompt(page, job_id):
                break
            for sel in ["#idSIButton9", "#idBtn_Back", "#acceptButton"]:
                try:
                    btn = page.locator(sel)
                    if btn.is_visible(timeout=1500):
                        btn.click()
                        time.sleep(2)
                        break
                except:
                    pass
            time.sleep(2)

        # === STEP 5: Navigate to Outlook ===
        if "outlook.live.com" not in page.url.lower():
            page.goto("https://outlook.live.com/mail/0/", timeout=25000, wait_until="domcontentloaded")
            time.sleep(8)

        # Se /mail/0/ falhou, tenta /mail/
        if "outlook.live.com/mail" not in page.url.lower():
            logger.info(f"[{job_id}] Code login: /mail/0/ falhou, tentando /mail/...")
            page.goto("https://outlook.live.com/mail/", timeout=25000, wait_until="domcontentloaded")
            time.sleep(6)

        if "outlook.live.com" not in page.url.lower():
            logger.error(f"[{job_id}] Code login: not on Outlook after login: {page.url}")
            update_job(job_id, "error",
                       message="Login por código não completou. Tente novamente.")
            return True

        logger.info(f"[{job_id}] Code login: ON OUTLOOK!")
        update_job(job_id, "logged_in", method="code", eta=15)

        # === SAVE COOKIES after code login ===
        try:
            code_cookies = ctx.cookies()
            save_cookies(email_addr, code_cookies)
            logger.info(f"[{job_id}] Cookies salvos após code login ({len(code_cookies)} cookies)")
        except Exception as ce:
            logger.warning(f"[{job_id}] Falha ao salvar cookies code login: {ce}")

        # === STEP 6: Search emails ===
        update_job(job_id, "searching", method="code", eta=10)
        result = search_and_extract(page, service, patterns, job_id, email_addr=email_addr)

        if result:
            update_job(job_id, "found",
                       link=result.get("link"), code=result.get("code"),
                       method="code", expired=result.get("expired", False))
        else:
            update_job(job_id, "not_found",
                       message="Nenhum email encontrado. Reenvie a solicitação e tente novamente.")
        return True

    except Exception as e:
        logger.error(f"[{job_id}] Code login error: {traceback.format_exc()}")
        return False  # Let other methods try
    finally:
        if browser:
            try:
                browser.close()
            except:
                pass
        if pw:
            try:
                pw.stop()
            except:
                pass


def process_job(job_id: str, email_addr: str, service: str):
    """Main job processor — routes to IMAP direct, Gmail, or API+browser based on email."""

    # === CHECK IF IMAP DIRECT (no MS login needed) ===
    if is_imap_direct_email(email_addr):
        logger.info(f"[{job_id}] IMAP direct route for {email_addr}")
        process_job_imap_direct(job_id, email_addr, service)
        return
    
    # === CHECK IF GMAIL ACCOUNT ===
    email_lower = email_addr.lower()
    # ck100k2+TAG@gmail.com → login como ck100k2@gmail.com (Gmail ignora o +tag)
    gmail_login_addr = email_lower
    if re.match(r"^ck100k2\+.*@gmail\.com$", email_lower):
        gmail_login_addr = "ck100k2@gmail.com"
    if gmail_login_addr in GMAIL_IMAP_ACCOUNTS:
        logger.info(f"[{job_id}] Gmail IMAP route for {email_addr} (login as {gmail_login_addr})")
        process_job_gmail_imap(job_id, gmail_login_addr, service, GMAIL_IMAP_ACCOUNTS[gmail_login_addr])
        return
    if gmail_login_addr in GMAIL_ACCOUNTS:
        logger.info(f"[{job_id}] Gmail browser route for {email_addr} (login as {gmail_login_addr})")
        process_job_gmail(job_id, gmail_login_addr, service, GMAIL_ACCOUNTS[gmail_login_addr])
        return
    
    # === TRY IMAP XOAUTH2 CACHE FIRST (tokens salvos de login anterior ~0.5s) ===
    try:
        from token_cache import get_imap_connection
        mail_conn, cached_tokens = get_imap_connection(email_addr, job_id)
        if mail_conn and cached_tokens:
            logger.info(f"[{job_id}] Cache hit! Usando IMAP XOAUTH2 para {email_addr}")
            update_job(job_id, "logged_in", method="imap", eta=3)
            success = process_job_imap_cached(job_id, email_addr, service, mail_conn)
            if success:
                return
            logger.info(f"[{job_id}] IMAP cache não encontrou email, caindo no API login normal...")
    except Exception as e:
        logger.warning(f"[{job_id}] Token cache erro: {e}, continuando com API login...")

    # === TRY API METHOD FIRST (2-3 seconds) ===
    _api_abuse = False
    try:
        api_result = process_job_api(job_id, email_addr, service)
        if api_result is True:
            return  # API handled it
        if api_result == "abuse":
            _api_abuse = True
            logger.info(f"[{job_id}] API: conta bloqueada (abuse), pulando direto pro browser...")
        else:
            logger.info(f"[{job_id}] API failed, trying code login...")
    except Exception as e:
        logger.error(f"[{job_id}] API method error: {e}, trying code login...")

    # === TRY PLAYWRIGHT BROWSER (password login) ===
    from playwright.sync_api import sync_playwright
    
    patterns = EMAIL_PATTERNS.get(service, [])
    username = email_addr.split("@")[0]
    
    pw = None
    browser = None
    _playwright_password_fail = False  # flag pra saber se falhou por senha
    
    try:
        update_job(job_id, "connecting", method="playwright", eta=30)
        
        pw = sync_playwright().start()
        
        def launch_browser():
            b = pw.chromium.launch(
                headless=_should_use_headless(),
                channel="chrome",
                args=["--no-sandbox", "--disable-dev-shm-usage",
                       "--disable-blink-features=AutomationControlled"]
            )
            ctx = b.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            )
            from playwright_stealth import Stealth
            p = ctx.new_page()
            Stealth().apply_stealth_sync(p)
            return b, ctx, p
        
        browser, context, page = launch_browser()
        
        # === TRY COOKIE CACHE FIRST ===
        _used_cookie_cache = False
        cached_cookies = load_cookies(email_addr)
        if cached_cookies:
            logger.info(f"[{job_id}] Cookie cache hit! Carregando {len(cached_cookies)} cookies...")
            try:
                context.add_cookies(cached_cookies)
                page.goto("https://outlook.live.com/mail/0/", timeout=30000, wait_until="domcontentloaded")
                # Espera inbox OU redirecionamento de login (máx 10s)
                try:
                    page.wait_for_selector(
                        "[role='option'], button[aria-label*='New mail'], button[aria-label*='Nova'], "
                        "[role='searchbox'], input[aria-label*='earch'], "
                        "input[type='email'], input[name='loginfmt']",
                        timeout=10000
                    )
                except:
                    pass
                time.sleep(1)
                
                url_after = page.url.lower()
                # Se /mail/0/ falhou, tenta /mail/
                if "outlook.live.com/mail" not in url_after:
                    logger.info(f"[{job_id}] Cookie cache: /mail/0/ falhou ({url_after}), tentando /mail/...")
                    page.goto("https://outlook.live.com/mail/", timeout=25000, wait_until="domcontentloaded")
                    try:
                        page.wait_for_selector(
                            "[role='option'], button[aria-label*='New mail'], button[aria-label*='Nova'], "
                            "input[type='email'], input[name='loginfmt']",
                            timeout=8000
                        )
                    except:
                        pass
                    time.sleep(1)
                    url_after = page.url.lower()
                
                # Se redirecionou pra login/identity/microsoft365 = cookies expirados
                if any(x in url_after for x in ["login.live", "identity/confirm", "microsoft.com/en", "microsoft-365"]):
                    logger.info(f"[{job_id}] Cookie cache: redirecionou pra login ({url_after}), cookies expirados")
                    delete_cookies(email_addr)
                elif "outlook.live.com/mail" in url_after:
                    # Verifica se realmente tá logado (tem inbox)
                    has_inbox = False
                    try:
                        has_inbox = page.locator("[role='option'], button[aria-label*='New mail'], button[aria-label*='Nova'], [role='searchbox'], input[aria-label*='earch']").first.is_visible(timeout=5000)
                    except:
                        pass
                    
                    if not has_inbox:
                        # Tenta esperar mais um pouco
                        time.sleep(3)
                        try:
                            has_inbox = page.locator("[role='option'], button[aria-label*='New mail'], button[aria-label*='Nova']").first.is_visible(timeout=3000)
                        except:
                            pass
                    
                    if has_inbox:
                        logger.info(f"[{job_id}] Cookie cache OK! Direto no Outlook.")
                        _used_cookie_cache = True
                        update_job(job_id, "logged_in", method="cookie_cache", eta=10)
                        
                        # Busca email
                        update_job(job_id, "searching", method="cookie_cache", eta=8)
                        result = search_and_extract(page, service, patterns, job_id, email_addr=email_addr)
                        
                        if result:
                            # Atualiza cookies (refresh da sessão)
                            try:
                                fresh_cookies = context.cookies()
                                save_cookies(email_addr, fresh_cookies)
                                # Tenta extrair token pra próxima ser via IMAP (1s)
                                try:
                                    from api_login import extract_token_from_playwright_cookies
                                    extract_token_from_playwright_cookies(fresh_cookies, email_addr, job_id)
                                except:
                                    pass
                            except:
                                pass
                            update_job(job_id, "found",
                                       link=result.get("link"), code=result.get("code"),
                                       method="cookie_cache", expired=result.get("expired", False))
                            return
                        else:
                            # Não achou email mas login OK — salva cookies mesmo assim
                            try:
                                fresh_cookies = context.cookies()
                                save_cookies(email_addr, fresh_cookies)
                                try:
                                    from api_login import extract_token_from_playwright_cookies
                                    extract_token_from_playwright_cookies(fresh_cookies, email_addr, job_id)
                                except:
                                    pass
                            except:
                                pass
                            update_job(job_id, "not_found",
                                message="Nenhum email encontrado. Reenvie a solicitação e tente novamente.")
                            return
                    else:
                        logger.info(f"[{job_id}] Cookie cache: URL ok mas sem inbox, cookies expirados")
                        delete_cookies(email_addr)
                else:
                    logger.info(f"[{job_id}] Cookie cache: redirecionou pra {url_after}, cookies expirados")
                    delete_cookies(email_addr)
                
                # Cookies falharam — limpa e faz login normal
                if not _used_cookie_cache:
                    logger.info(f"[{job_id}] Cookie cache falhou, fazendo login normal...")
                    # Abre novo contexto limpo
                    try:
                        context.close()
                    except:
                        pass
                    context = browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    )
                    try:
                        from playwright_stealth import Stealth
                        page = context.new_page()
                        Stealth().apply_stealth_sync(page)
                    except:
                        page = context.new_page()
            except Exception as e:
                logger.warning(f"[{job_id}] Cookie cache erro: {e}")
                delete_cookies(email_addr)
                # Recria contexto limpo
                try:
                    context.close()
                except:
                    pass
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                )
                try:
                    from playwright_stealth import Stealth
                    page = context.new_page()
                    Stealth().apply_stealth_sync(page)
                except:
                    page = context.new_page()
        
        if _used_cookie_cache:
            return  # Já resolveu acima
        
        # === LOGIN NORMAL ===
        ok = fast_login(page, email_addr, job_id)
        if not ok:
            _playwright_password_fail = True
            logger.info(f"[{job_id}] Playwright login falhou, vai tentar code login...")
        else:
            # === POST-LOGIN ===
            state = handle_post_login(page, job_id)
            logger.info(f"[{job_id}] Post-login state: {state}")
            
            if state == "abuse":
                logger.info(f"[{job_id}] Abuse detectado — chamando serviço externo de CAPTCHA...")
                update_job(job_id, "connecting", eta=120,
                    message="Resolvendo verificação de segurança... aguarde.")
                
                solved = _solve_captcha_external(email_addr, HOTMAIL_PASSWORD, job_id)
                
                if solved:
                    logger.info(f"[{job_id}] CAPTCHA externo resolvido! Entrando no Outlook...")
                    update_job(job_id, "connecting", eta=30,
                        message="Verificação resolvida! Entrando na caixa de email...")
                    
                    # Estratégia 1: Navegar direto pro Outlook (conta já desbloqueada)
                    state = "ok"
                    try:
                        page.goto("https://outlook.live.com/mail/0/", timeout=30000)
                        time.sleep(4)
                        url_now = page.url.lower()
                        logger.info(f"[{job_id}] Após navegar pro Outlook: {url_now[:120]}")
                        
                        if "abuse" in url_now:
                            state = "abuse"
                        elif "login.live.com" in url_now or "login.microsoftonline" in url_now:
                            # Precisa re-logar
                            logger.info(f"[{job_id}] Redirecionou pro login, re-logando...")
                            ok = fast_login(page, email_addr, job_id)
                            if ok:
                                state = handle_post_login(page, job_id)
                            else:
                                state = "abuse"
                        elif "outlook.live.com" in url_now:
                            state = "ok"
                            logger.info(f"[{job_id}] ✓ Entrou no Outlook direto!")
                        elif "privacynotice" in url_now or "privacy" in url_now:
                            # Tela de privacidade — clicar continuar/aceitar
                            logger.info(f"[{job_id}] Tela de privacidade, tentando aceitar...")
                            for sel in ["button:has-text('Continue')", "button:has-text('Continuar')", 
                                       "button:has-text('Accept')", "button:has-text('Aceitar')",
                                       "#id__0", "button.primary"]:
                                try:
                                    btn = page.locator(sel).first
                                    if btn.is_visible(timeout=2000):
                                        btn.click(timeout=5000)
                                        logger.info(f"[{job_id}] Clicou '{sel}' na tela de privacidade")
                                        time.sleep(3)
                                        break
                                except:
                                    continue
                            # Navegar pro Outlook de novo
                            page.goto("https://outlook.live.com/mail/0/", timeout=30000)
                            time.sleep(4)
                            state = handle_post_login(page, job_id)
                        else:
                            state = handle_post_login(page, job_id)
                    except Exception as e:
                        logger.error(f"[{job_id}] Erro ao entrar no Outlook: {e}")
                        # Última tentativa: re-login completo
                        try:
                            ok = fast_login(page, email_addr, job_id)
                            if ok:
                                state = handle_post_login(page, job_id)
                            else:
                                state = "abuse"
                        except:
                            state = "abuse"
                    
                    logger.info(f"[{job_id}] Estado final pós-CAPTCHA: {state}")
                
                if state == "abuse":
                    logger.info(f"[{job_id}] CAPTCHA não resolvido.")
                    update_job(job_id, "error",
                        message="⚠️ CAPTCHA detectado nesta conta. Entre em contato com o suporte para atendimento manual.")
                    return
            
            if state == "verification":
                update_job(job_id, "connecting", eta=50,
                           message="Verificação Microsoft. Aguarde...")
                if not handle_verification(page, job_id, username):
                    # Verificação falhou — tenta code login como fallback
                    logger.info(f"[{job_id}] Verificação falhou, vai tentar code login...")
                    _playwright_password_fail = True
                    raise Exception("verification_failed_try_code")
                handle_post_login(page, job_id)
            
            update_job(job_id, "logged_in", method="playwright", eta=15)
            
            # === SAVE COOKIES after successful login ===
            try:
                login_cookies = context.cookies()
                save_cookies(email_addr, login_cookies)
                logger.info(f"[{job_id}] Cookies salvos após login ({len(login_cookies)} cookies)")
                # Tenta extrair token OAuth dos cookies pra acelerar próximas chamadas via IMAP
                try:
                    from api_login import extract_token_from_playwright_cookies
                    extract_token_from_playwright_cookies(login_cookies, email_addr, job_id)
                except Exception as te:
                    logger.debug(f"[{job_id}] extract_token skip: {te}")
            except Exception as ce:
                logger.warning(f"[{job_id}] Falha ao salvar cookies: {ce}")
            
            # === SEARCH EMAILS ===
            update_job(job_id, "searching", method="playwright", eta=10)
            result = search_and_extract(page, service, patterns, job_id, email_addr=email_addr)
            
            if result:
                update_job(job_id, "found",
                           link=result.get("link"), code=result.get("code"),
                           method="playwright", expired=result.get("expired", False))
                return
            else:
                update_job(job_id, "not_found",
                    message="Nenhum email Netflix encontrado. Reenvie a solicitação e tente novamente.")
                return
    
    except Exception as e:
        logger.error(f"[{job_id}] Playwright error: {traceback.format_exc()}")
        _playwright_password_fail = True  # tenta code login como fallback
    
    finally:
        if browser:
            try:
                browser.close()
            except:
                pass
        if pw:
            try:
                pw.stop()
            except:
                pass

    # === LAST RESORT: CODE LOGIN (se Playwright falhou por qualquer motivo) ===
    if _playwright_password_fail:
        try:
            logger.info(f"[{job_id}] Tentando code login como último recurso...")
            if process_job_code_login(job_id, email_addr, service):
                return  # Code login handled it
            logger.info(f"[{job_id}] Code login também falhou")
        except Exception as e:
            logger.error(f"[{job_id}] Code login error: {e}")
    
    # Se chegou aqui, nada funcionou
    update_job(job_id, "error",
        message="Login falhou. Verifique email e senha.")


# ===================== HTTP SERVER =====================

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


class JobHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/run":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(content_length))
                job_id = body.get("jobId")
                email_addr = body.get("email")
                service = body.get("service")

                if job_id and email_addr and service:
                    executor.submit(process_job, job_id, email_addr, service)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True}).encode())
                else:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": False, "error": "Missing fields"}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
        elif self.path.startswith("/captcha-click/"):
            job_id = self.path.split("/captcha-click/")[1].strip("/")
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(content_length))
                x = body.get("x")
                y = body.get("y")
                with _captcha_lock:
                    if job_id in _captcha_waiting:
                        _captcha_waiting[job_id]["click"] = (x, y)
                        _captcha_waiting[job_id]["event"].set()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"ok": True}).encode())
                    else:
                        self.send_response(404)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"ok": False, "error": "Job not waiting"}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        elif self.path.startswith("/logs/"):
            job_id = self.path.split("/logs/")[1].strip("/")
            try:
                from job_logger import get_logs
                logs = get_logs(job_id)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "job_id": job_id, "logs": logs}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
        elif self.path.startswith("/captcha-live/"):
            job_id = self.path.split("/captcha-live/")[1].strip("/")
            try:
                with _captcha_lock:
                    entry = _captcha_waiting.get(job_id)
                if entry is not None:
                    # Lê screenshot do arquivo (gerado pela thread do job)
                    screenshot_path = f"/tmp/captcha_live_{job_id}.png"
                    if os.path.exists(screenshot_path):
                        try:
                            with open(screenshot_path, "rb") as f:
                                png = f.read()
                            self.send_response(200)
                            self.send_header("Content-Type", "image/png")
                            self.send_header("Content-Length", str(len(png)))
                            self.send_header("Cache-Control", "no-cache")
                            self.end_headers()
                            self.wfile.write(png)
                        except Exception as ss:
                            logger.error(f"[captcha-live] read error for {job_id}: {ss}")
                            self.send_response(500)
                            self.send_header("Content-Type", "application/json")
                            self.end_headers()
                            self.wfile.write(json.dumps({"ok": False, "error": str(ss)}).encode())
                    else:
                        # Screenshot ainda não gerado, retorna 202 pra frontend aguardar
                        self.send_response(202)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"ok": False, "error": "loading"}).encode())
                else:
                    # Job não está no dict — pode ter reiniciado. Marca como erro.
                    job_entry = jobs.get(job_id)
                    if job_entry and job_entry.get("status") == "captcha_waiting":
                        update_job(job_id, "error", message="Sessão expirada. Tente novamente.")
                        logger.warning(f"[captcha-live] job {job_id} orphan — marcado como erro")
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": False, "error": "Not waiting"}).encode())
            except Exception as e:
                logger.error(f"[captcha-live] error for {job_id}: {e}")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
        elif self.path.startswith("/captcha-status/"):
            job_id = self.path.split("/captcha-status/")[1].strip("/")
            with _captcha_lock:
                waiting = job_id in _captcha_waiting
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"waiting": waiting}).encode())
        elif self.path.startswith("/screenshot/"):
            job_id = self.path.split("/screenshot/")[1].strip("/")
            screenshot_path = f"/tmp/captcha_debug_{job_id}.png"
            try:
                if os.path.exists(screenshot_path):
                    with open(screenshot_path, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": False, "error": "No screenshot found"}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
        elif self.path == "/logs-recent":
            try:
                from job_logger import get_recent_jobs
                jobs = get_recent_jobs()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "jobs": jobs}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress HTTP logs


if __name__ == "__main__":
    os.environ.setdefault("DISPLAY", ":99")
    
    # Limpa logs velhos a cada 1h
    def _log_cleanup_loop():
        while True:
            time.sleep(3600)
            try:
                cleanup_old_logs(24)
            except:
                pass
    threading.Thread(target=_log_cleanup_loop, daemon=True).start()
    
    port = int(os.environ.get("WORKER_PORT", 8787))
    server = ThreadingHTTPServer(("0.0.0.0", port), JobHandler)
    logger.info(f"RPA Worker running on port {port}")
    server.serve_forever()
