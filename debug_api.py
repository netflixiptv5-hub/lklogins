import sys, re, json, urllib.parse, gzip
from io import BytesIO
sys.path.insert(0, 'worker')
import httpx

CLIENT_ID = 'e9b154d0-7658-433b-bb25-6b8e0a8a7c59'
REDIRECT_URI = 'msauth://com.microsoft.outlooklite/fcg80qvoM1YMKJZibjBwQcDfOno%3D'
SCOPE = 'profile openid offline_access https://outlook.office.com/M365.Access'
UA = 'Mozilla/5.0 (Linux; Android 9) AppleWebKit/537.36 Chrome/91.0.4472.114 Mobile Safari/537.36'
UA_AUTH = UA + ' PKeyAuth/1.0'
email = 'arthurgabrielcirino02122004@hotmail.com'
password = '02022013L'

client = httpx.Client(follow_redirects=True, timeout=30, headers={'Accept-Encoding': 'gzip, deflate'})

auth_url = (
    f"https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize?"
    f"client_info=1&haschrome=1&login_hint={urllib.parse.quote(email)}"
    f"&client_id={CLIENT_ID}&mkt=en&response_type=code"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
    f"&scope={urllib.parse.quote(SCOPE)}"
)

r1 = client.get(auth_url, headers={'User-Agent': UA, 'X-Requested-With': 'com.microsoft.outlooklite'})
body1 = r1.text

ppft = None
for pattern in [
    r'sFTTag.*?value=\\"([^\\]+)',
    r'name="PPFT"[^>]*value="([^"]+)"',
    r'"sFT"\s*:\s*"([^"]+)"',
]:
    m = re.search(pattern, body1)
    if m:
        ppft = m.group(1)
        break

urlpost = re.search(r'"urlPost"\s*:\s*"([^"]+)"', body1).group(1)
print(f"PPFT: {ppft[:30]}...")
print(f"urlPost: {urlpost[:80]}...")

post_data = (
    f"i13=1&login={urllib.parse.quote(email)}&loginfmt={urllib.parse.quote(email)}"
    f"&type=11&LoginOptions=1&passwd={urllib.parse.quote(password)}&ps=2"
    f"&PPFT={urllib.parse.quote(ppft)}&PPSX=Passport&NewUser=1"
    f"&fspost=0&i21=0&CookieDisclosure=0&IsFidoSupported=0"
    f"&isSignupPost=0&isRecoveryAttemptPost=0&i19=3772"
)

r2 = client.post(urlpost, content=post_data, follow_redirects=False, headers={
    'User-Agent': UA_AUTH,
    'Content-Type': 'application/x-www-form-urlencoded',
    'X-Requested-With': 'com.microsoft.outlooklite',
})

body2 = r2.text
print(f"\nStatus: {r2.status_code}")
print(f"Location: {r2.headers.get('location', 'none')[:200]}")

# Check for identity confirm
if 'identity/confirm' in body2 or 'identity/confirm' in str(r2.headers.get('location', '')):
    print("\n=== IDENTITY CONFIRM DETECTED ===")

# Look for masked emails
masked = re.findall(r'[a-zA-Z0-9]{1,8}\*+@[a-zA-Z0-9.*]+', body2)
print(f"\nMasked emails found: {masked}")

# Look for proof info in JSON
proof_matches = re.findall(r'"(isNopa|proof|Proof|recovery|Recovery|Email|Phone|SMS)[^"]*"\s*:\s*"?([^",}{]+)', body2, re.IGNORECASE)
print(f"Proof hints: {proof_matches[:10]}")

# Save body
with open('/tmp/ms_verify_body.html', 'w') as f:
    f.write(body2)
print(f"\nBody saved: {len(body2)} chars")

# Check specific patterns
for kw in ['identity/confirm', 'proofs/Add', 'fmHF', 'kmsi', 'identity', 'proofs', 'abuse', 'cancel']:
    if kw in body2.lower():
        print(f"  Found: '{kw}'")
