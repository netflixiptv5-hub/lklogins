"""
Hotmail API Login + Email Search — based on OpenBullet Outlook Lite OAuth flow.
No browser needed. ~2-3s total.
"""

import re
import json
import time
import gzip
import logging
import urllib.parse
from io import BytesIO
import httpx

logger = logging.getLogger("rpa")

# Outlook Lite OAuth config
CLIENT_ID = "e9b154d0-7658-433b-bb25-6b8e0a8a7c59"
REDIRECT_URI = "msauth://com.microsoft.outlooklite/fcg80qvoM1YMKJZibjBwQcDfOno%3D"
SCOPE = "profile openid offline_access https://outlook.office.com/M365.Access"
USER_AGENT = "Mozilla/5.0 (Linux; Android 9; V2218A Build/PQ3B.190801.08041932; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/91.0.4472.114 Mobile Safari/537.36"
USER_AGENT_AUTH = USER_AGENT + " PKeyAuth/1.0"

PASSWORDS = ["02022013L", "A29b92c10@"]


def _decompress(response):
    """Handle gzip responses."""
    if response.headers.get("content-encoding") == "gzip":
        try:
            return gzip.GzipFile(fileobj=BytesIO(response.content)).read().decode("utf-8", errors="replace")
        except:
            pass
    return response.text


def api_login(email: str, job_id: str = "") -> dict | None:
    """
    Login to Hotmail via Outlook Lite OAuth API flow.
    Returns {"access_token": str, "cid": str} on success, None on failure.
    """
    username = email.strip()
    
    for password in PASSWORDS:
        result = _try_login(username, password, job_id)
        if result:
            return result
        logger.info(f"[{job_id}] API login failed with password, trying next...")
    
    logger.error(f"[{job_id}] API login: all passwords failed")
    return None


def _try_login(email: str, password: str, job_id: str) -> dict | None:
    """Single login attempt."""
    client = httpx.Client(
        follow_redirects=True,
        timeout=30,
        headers={"Accept-Encoding": "gzip, deflate"},
    )
    
    try:
        # === STEP 1: Authorize — get PPFT and urlPost ===
        auth_url = (
            f"https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?"
            f"client_info=1&haschrome=1&login_hint={urllib.parse.quote(email)}"
            f"&client_id={CLIENT_ID}&mkt=en"
            f"&response_type=code"
            f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
            f"&scope={urllib.parse.quote(SCOPE)}"
        )
        
        r1 = client.get(auth_url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "X-Requested-With": "com.microsoft.outlooklite",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
        })
        
        body1 = _decompress(r1)
        
        # Check if account exists
        if '"IfExistsResult":1' in body1 or '"ErrorHR":"80041103"' in body1:
            logger.error(f"[{job_id}] Account does not exist: {email}")
            return None
        
        # Parse PPFT/sFT (modern MS login embeds in JS with escaped quotes)
        ppft = None
        for pattern in [
            r'sFTTag.*?value=\\"([^\\]+)',       # sFTTag: <input...value=\"TOKEN\"
            r'name="PPFT"[^>]*value="([^"]+)"',  # classic HTML form
            r'"sFT"\s*:\s*"([^"]+)"',             # JSON config
            r'PPFT.*?value=\\"([^\\]+)',           # PPFT with escaped quotes
        ]:
            ppft_match = re.search(pattern, body1)
            if ppft_match:
                ppft = ppft_match.group(1)
                break
        
        if not ppft:
            logger.error(f"[{job_id}] PPFT not found")
            return None
        
        # Parse urlPost
        urlpost_match = re.search(r'"urlPost"\s*:\s*"([^"]+)"', body1)
        if not urlpost_match:
            # Try escaped variant
            urlpost_match = re.search(r'"urlPost"\s*:\s*\\"([^\\]+)', body1)
        if not urlpost_match:
            logger.error(f"[{job_id}] urlPost not found")
            return None
        url_post = urlpost_match.group(1)
        
        logger.info(f"[{job_id}] API Step 1 OK: got PPFT + urlPost")
        
        # Collect cookies from step 1
        cookies = dict(client.cookies)
        
        # === STEP 2: POST login ===
        post_data = (
            f"i13=1&login={urllib.parse.quote(email)}&loginfmt={urllib.parse.quote(email)}"
            f"&type=11&LoginOptions=1&lrt=&lrtPartition=&hisRegion=&hisScaleUnit="
            f"&passwd={urllib.parse.quote(password)}&ps=2"
            f"&psRNGCDefaultType=&psRNGCEntropy=&psRNGCSLK=&canary=&ctx=&hpgrequestid="
            f"&PPFT={urllib.parse.quote(ppft)}&PPSX=Passport&NewUser=1&FoundMSAs="
            f"&fspost=0&i21=0&CookieDisclosure=0&IsFidoSupported=0"
            f"&isSignupPost=0&isRecoveryAttemptPost=0&i19=3772"
        )
        
        # Disable redirects for login POST to capture Location header
        r2 = client.post(url_post, content=post_data, follow_redirects=False, headers={
            "User-Agent": USER_AGENT_AUTH,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "X-Requested-With": "com.microsoft.outlooklite",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Origin": "https://login.live.com",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
        })
        
        body2 = _decompress(r2)
        all_cookies = dict(client.cookies)
        
        # Check login result
        if "account or password is incorrect" in body2:
            logger.info(f"[{job_id}] Wrong password")
            return None
        
        if "too many times with" in body2:
            logger.warning(f"[{job_id}] Account rate limited")
            return None
        
        if "identity/confirm" in body2 or "identity/confirm" in str(r2.headers.get("location", "")):
            logger.warning(f"[{job_id}] API: needs identity verification (fallback to browser)")
            return {"error": "verification_needed"}
        
        if "/Abuse" in body2 or "finisherror.srf" in str(r2.headers.get("location", "")):
            logger.warning(f"[{job_id}] API: abuse/blocked")
            return {"error": "abuse"}
        
        if "/recover" in body2:
            logger.warning(f"[{job_id}] API: account recovery needed")
            return {"error": "recovery"}
        
        # Check success indicators
        has_jsh = "JSH" in str(all_cookies) or "JSHP" in str(all_cookies)
        has_consent = 'action="https://account.live.com/Consent/Update' in body2
        loc2_header = r2.headers.get("location", "")
        is_redirect = "oauth20_desktop.srf" in loc2_header or "msauth://" in loc2_header
        has_cancel = "/cancel?mkt" in body2
        has_kmsi = "fmHF" in body2 or "kmsi" in body2.lower() or "stay signed in" in body2.lower()
        has_new_urlpost = '"urlPost"' in body2 and '"sFT"' not in body2[:500]
        
        logger.info(f"[{job_id}] API Step 2: jsh={has_jsh}, consent={has_consent}, redirect={is_redirect}, cancel={has_cancel}, kmsi={has_kmsi}")
        
        # KMSI (Keep Me Signed In) page — need to POST again
        if has_kmsi and not (has_jsh or is_redirect or has_cancel):
            logger.info(f"[{job_id}] Auto-submit form detected")
            
            # Parse fmHF auto-submit form
            form_action = re.search(r'action="([^"]+)"', body2)
            hidden_fields = re.findall(r'<input type="hidden" name="([^"]+)"[^>]*value="([^"]*)"', body2)
            
            if form_action:
                action_url = form_action.group(1)
                
                # For proofs/Add or identity/confirm — try submitting anyway (skip/remind later)
                if "proofs/Add" in action_url or "identity/confirm" in action_url:
                    logger.info(f"[{job_id}] API: proofs page detected, attempting to skip...")
                    # Try submitting the form — MS often allows skipping
                    form_data = "&".join(f"{urllib.parse.quote(n)}={urllib.parse.quote(v)}" for n, v in hidden_fields)
                    # Add iLandingViewAction=0 to try "remind me later"
                    form_data += "&iLandingViewAction=0"
                    r2b = client.post(action_url, content=form_data, follow_redirects=True, headers={
                        "User-Agent": USER_AGENT_AUTH,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-Requested-With": "com.microsoft.outlooklite",
                    })
                    body2b = _decompress(r2b)
                    loc2b = r2b.headers.get("location", "")
                    all_cookies_b = dict(client.cookies)
                    
                    # Check if we got past proofs
                    code_match = re.search(r"code=([^&\s]+)", str(r2b.url) + loc2b)
                    has_cancel_b = "/cancel?mkt" in body2b
                    has_redirect_b = "oauth20_desktop.srf" in loc2b or "msauth://" in loc2b or "oauth20_desktop.srf" in str(r2b.url)
                    
                    if code_match:
                        logger.info(f"[{job_id}] API: proofs skipped! Got code directly")
                        # Jump straight to token exchange
                        code = code_match.group(1)
                        all_cookies = all_cookies_b
                        # Skip to step 4 below
                    elif has_cancel_b or has_redirect_b:
                        logger.info(f"[{job_id}] API: proofs skipped, got cancel/redirect page")
                        body2 = body2b
                        all_cookies = all_cookies_b
                        loc2_header = loc2b
                        r2 = r2b
                        has_jsh = "JSH" in str(all_cookies) or "JSHP" in str(all_cookies)
                        has_consent = 'action="https://account.live.com/Consent/Update' in body2
                        is_redirect = "oauth20_desktop.srf" in loc2_header or "msauth://" in loc2_header
                        has_cancel = has_cancel_b
                    else:
                        # Still on proofs page — need browser
                        logger.warning(f"[{job_id}] API: could not skip proofs, fallback to browser")
                        return {"error": "proofs_needed"}
                else:
                    # Regular form submit (consent, KMSI, etc.)
                    form_data = "&".join(f"{urllib.parse.quote(n)}={urllib.parse.quote(v)}" for n, v in hidden_fields)
                    r2b = client.post(action_url, content=form_data, follow_redirects=False, headers={
                        "User-Agent": USER_AGENT_AUTH,
                        "Content-Type": "application/x-www-form-urlencoded",
                        "X-Requested-With": "com.microsoft.outlooklite",
                    })
                    body2 = _decompress(r2b)
                    all_cookies = dict(client.cookies)
                    loc2_header = r2b.headers.get("location", "")
                    has_jsh = "JSH" in str(all_cookies) or "JSHP" in str(all_cookies)
                    has_consent = 'action="https://account.live.com/Consent/Update' in body2
                    is_redirect = "oauth20_desktop.srf" in loc2_header or "msauth://" in loc2_header
                    has_cancel = "/cancel?mkt" in body2
                    r2 = r2b
                    logger.info(f"[{job_id}] After form submit: jsh={has_jsh}, redirect={is_redirect}, cancel={has_cancel}")
        
        if not (has_jsh or has_consent or is_redirect or has_cancel):
            logger.error(f"[{job_id}] Login failed — no success indicators")
            return None
        
        # === STEP 2.5: Handle consent/cancel page ===
        # code may already be set from proofs skip
        if 'code' not in dir() or not code:
            code = None
        
        # Check Location header for redirect with code (302 response)
        loc2 = r2.headers.get("location", "")
        if loc2:
            code_match = re.search(r"code=([^&\s]+)", loc2)
            if code_match:
                code = code_match.group(1)
                logger.info(f"[{job_id}] Got code from login redirect")
        
        if is_redirect and not code:
            # Follow the redirect to get code
            loc = r2.headers.get("location", "")
            code_match = re.search(r"code=([^&]+)", loc)
            if code_match:
                code = code_match.group(1)
        
        if not code and has_cancel:
            # Parse opid, opidt, uaid from page
            opidt_match = re.search(r'opidt%3d([^"&]+)', body2)
            opid_match = re.search(r'opid%3d([^%"&]+)', body2)
            uaid_match = re.search(r'name="uaid"[^>]*value="([^"]+)"', body2)
            
            if opid_match and uaid_match:
                opidt = opidt_match.group(1) if opidt_match else ""
                opid = opid_match.group(1)
                uaid = uaid_match.group(1)
                
                oauth_url = (
                    f"https://login.live.com/oauth20_authorize.srf?"
                    f"uaid={uaid}&client_id={CLIENT_ID}"
                    f"&opid={opid}&mkt=EN-US&opidt={opidt}"
                    f"&res=success&route=C105_BAY"
                )
                
                r3 = client.get(oauth_url, follow_redirects=False, headers={
                    "User-Agent": USER_AGENT_AUTH,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "X-Requested-With": "com.microsoft.outlooklite",
                    "Sec-Fetch-Site": "same-site",
                    "Sec-Fetch-Mode": "navigate",
                    "Referer": "https://account.live.com/",
                })
                
                loc3 = r3.headers.get("location", "")
                code_match = re.search(r"code=([^&]+)", loc3)
                if code_match:
                    code = code_match.group(1)
                else:
                    body3 = _decompress(r3)
                    # Check for errors
                    if "/identity/confirm" in body3 or "/identity/confirm" in loc3:
                        return {"error": "verification_needed"}
                    if "/Abuse" in body3 or "/Abuse" in loc3:
                        return {"error": "abuse"}
                    logger.error(f"[{job_id}] No code in step 3, loc={loc3[:100]}")
                    return None
        
        if not code:
            logger.error(f"[{job_id}] Could not get authorization code")
            return None
        
        logger.info(f"[{job_id}] API Step 3 OK: got auth code")
        
        # === STEP 4: Exchange code for access token ===
        # The code captured from Location header may be URL-encoded (contains %24, *, ! etc.)
        # Must decode first, then re-encode cleanly for the POST body
        code_clean = urllib.parse.unquote(code)
        token_data = (
            f"client_info=1&client_id={CLIENT_ID}"
            f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
            f"&grant_type=authorization_code"
            f"&code={urllib.parse.quote(code_clean, safe='')}"
            f"&scope={urllib.parse.quote(SCOPE)}"
        )
        
        r4 = client.post(
            "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
            content=token_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "User-Agent": "Mozilla/5.0 (compatible; MSAL 1.0)",
                "x-client-Ver": "1.0.0+635e350c",
                "x-client-OS": "28",
                "x-client-SKU": "MSAL.xplat.android",
            },
        )
        
        token_body = r4.json()
        access_token = token_body.get("access_token")
        refresh_token = token_body.get("refresh_token", "")
        
        if not access_token:
            logger.error(f"[{job_id}] No access_token in response: {str(token_body)[:200]}")
            return None
        
        # Get CID from cookies
        cid = all_cookies.get("MSPCID", "").upper()
        
        logger.info(f"[{job_id}] API Step 4 OK: got access_token + CID={cid}")
        
        # Salva tokens no cache para próximos acessos via IMAP XOAUTH2
        try:
            from token_cache import save_tokens
            save_tokens(email, access_token, refresh_token, cid)
        except Exception as e:
            logger.warning(f"[{job_id}] Não foi possível salvar tokens no cache: {e}")
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "cid": cid,
            "client": client,
        }
    
    except Exception as e:
        logger.error(f"[{job_id}] API login error: {e}")
        return None
    finally:
        pass  # Keep client alive if successful


def api_search_emails(access_token: str, cid: str, keyword: str, job_id: str = "") -> list:
    """
    Search emails via Outlook REST API.
    Returns list of conversation snippets.
    """
    search_url = "https://outlook.live.com/search/api/v2/query?n=124"
    
    payload = {
        "Cvid": "7ef2720e-6e59-ee2b-a217-3a4f427ab0f7",
        "Scenario": {"Name": "owa.react"},
        "TimeZone": "E. South America Standard Time",
        "TextDecorations": "Off",
        "EntityRequests": [{
            "EntityType": "Conversation",
            "ContentSources": ["Exchange"],
            "Filter": {
                "Or": [
                    {"Term": {"DistinguishedFolderName": "msgfolderroot"}},
                    {"Term": {"DistinguishedFolderName": "DeletedItems"}},
                ]
            },
            "From": 0,
            "Query": {"QueryString": keyword},
            "RefiningQueries": None,
            "Size": 25,
            "Sort": [
                {"Field": "Score", "SortDirection": "Desc", "Count": 3},
                {"Field": "Time", "SortDirection": "Desc"},
            ],
            "EnableTopResults": True,
            "TopResultsCount": 3,
        }],
        "QueryAlterationOptions": {
            "EnableSuggestion": True,
            "EnableAlteration": True,
        },
        "LogicalId": "446c567a-02d9-b739-b9ca-616e0d45905c",
    }
    
    try:
        r = httpx.post(search_url, json=payload, headers={
            "User-Agent": "Outlook-Android/2.0",
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "X-AnchorMailbox": f"CID:{cid}",
        }, timeout=30)
        
        data = r.json()
        logger.info(f"[{job_id}] API search response keys: {list(data.keys()) if isinstance(data, dict) else 'not dict'}")
        return data
    
    except Exception as e:
        logger.error(f"[{job_id}] API search error: {e}")
        return {}


def api_get_email_content(access_token: str, cid: str, message_id: str, job_id: str = "") -> str:
    """Get full email body via Outlook REST API."""
    try:
        url = f"https://outlook.live.com/owa/0/api/2.0/me/messages/{message_id}"
        r = httpx.get(url, headers={
            "User-Agent": "Outlook-Android/2.0",
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "X-AnchorMailbox": f"CID:{cid}",
        }, timeout=30)
        
        data = r.json()
        body = data.get("Body", {}).get("Content", "")
        return body
    except Exception as e:
        logger.error(f"[{job_id}] API get email error: {e}")
        return ""


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    import sys
    email = sys.argv[1] if len(sys.argv) > 1 else "noahcassiano19062003@hotmail.com"
    keyword = sys.argv[2] if len(sys.argv) > 2 else "Netflix"
    
    print(f"\n=== Testing API login for {email} ===")
    result = api_login(email, "test")
    
    if result and "access_token" in result:
        print(f"✓ Login OK! Token: {result['access_token'][:50]}...")
        print(f"✓ CID: {result['cid']}")
        
        print(f"\n=== Searching for '{keyword}' ===")
        search_result = api_search_emails(result["access_token"], result["cid"], keyword, "test")
        print(json.dumps(search_result, indent=2)[:2000])
    elif result and "error" in result:
        print(f"✗ Login error: {result['error']}")
    else:
        print("✗ Login failed completely")
