import sys, re, json, urllib.parse
sys.path.insert(0, 'worker')
import httpx

# Extract form data from the identity/confirm page
form_action = "https://account.live.com/identity/confirm?mkt=EN-US&uiflavor=host&client_id=1E00004C7D3B3E&id=292841&ru=https://login.live.com/oauth20_authorize.srf%3fuaid%3d2660627bb95048b092273f8792cc7bac%26client_id%3de9b154d0-7658-433b-bb25-6b8e0a8a7c59%26opid%3dC46BA9A9E7DC151F%26mkt%3dEN-US%26opidt%3d1775752562"

# We need to POST the form with pprid, ipt, uaid
# But we need cookies from the login flow first
# Let's redo the whole flow

CLIENT_ID = 'e9b154d0-7658-433b-bb25-6b8e0a8a7c59'
REDIRECT_URI = 'msauth://com.microsoft.outlooklite/fcg80qvoM1YMKJZibjBwQcDfOno%3D'
SCOPE = 'profile openid offline_access https://outlook.office.com/M365.Access'
UA = 'Mozilla/5.0 (Linux; Android 9) AppleWebKit/537.36 Chrome/91.0.4472.114 Mobile Safari/537.36'
UA_AUTH = UA + ' PKeyAuth/1.0'
email = 'arthurgabrielcirino02122004@hotmail.com'
password = '02022013L'

client = httpx.Client(follow_redirects=True, timeout=30)

# Step 1
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

# Step 2: login
post_data = (
    f"i13=1&login={urllib.parse.quote(email)}&loginfmt={urllib.parse.quote(email)}"
    f"&type=11&LoginOptions=1&passwd={urllib.parse.quote(password)}&ps=2"
    f"&PPFT={urllib.parse.quote(ppft)}&PPSX=Passport&NewUser=1"
    f"&fspost=0&i21=0&CookieDisclosure=0&IsFidoSupported=0"
    f"&isSignupPost=0&isRecoveryAttemptPost=0&i19=3772"
)

# Don't follow redirects for login POST
r2 = client.post(urlpost, content=post_data, follow_redirects=False, headers={
    'User-Agent': UA_AUTH,
    'Content-Type': 'application/x-www-form-urlencoded',
    'X-Requested-With': 'com.microsoft.outlooklite',
})
body2 = r2.text

# Step 3: follow the identity/confirm redirect
# Parse hidden fields
pprid = re.search(r'name="pprid"[^>]*value="([^"]+)"', body2)
ipt = re.search(r'name="ipt"[^>]*value="([^"]+)"', body2)
uaid = re.search(r'name="uaid"[^>]*value="([^"]+)"', body2)
action = re.search(r'action="([^"]+)"', body2)

if action and pprid and ipt and uaid:
    print(f"Following identity/confirm redirect...")
    
    r3 = client.post(action.group(1), data={
        'pprid': pprid.group(1),
        'ipt': ipt.group(1),
        'uaid': uaid.group(1),
    }, headers={
        'User-Agent': UA_AUTH,
        'Content-Type': 'application/x-www-form-urlencoded',
    })
    
    body3 = r3.text
    print(f"Status: {r3.status_code}")
    print(f"URL: {r3.url}")
    print(f"Body length: {len(body3)}")
    
    # Look for masked emails / proof options
    masked = re.findall(r'[a-zA-Z0-9.]{1,8}\*+@[a-zA-Z0-9.*]+', body3)
    print(f"\nMasked emails: {masked}")
    
    # Look for proof/recovery options in JSON
    json_config = re.search(r'var\s+ServerData\s*=\s*(\{.*?\});', body3, re.DOTALL)
    if json_config:
        try:
            # This might not be valid JSON, but let's try to extract proof info
            config_text = json_config.group(1)[:5000]
            proofs = re.findall(r'"(proof|Proof|email|Email|phone|Phone|recovery|display|Display)[^"]*"\s*:\s*"?([^",}{]+)', config_text, re.IGNORECASE)
            print(f"Proof data: {proofs[:20]}")
        except:
            pass
    
    # Save for analysis
    with open('/tmp/ms_identity_page.html', 'w') as f:
        f.write(body3)
    print(f"\nSaved to /tmp/ms_identity_page.html")
    
    # Quick scan for key strings
    for kw in ['email', 'phone', 'sms', 'proof', 'recovery', 'send code', 'verify', 'protect']:
        if kw in body3.lower():
            print(f"  Contains: '{kw}'")
else:
    print("Could not parse identity/confirm form")
    print(f"Action: {action}")
    print(f"pprid: {pprid}")
