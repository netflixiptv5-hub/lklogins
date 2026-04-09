import sys, os, time, re
os.environ['DISPLAY'] = ':99'
import subprocess
subprocess.Popen(['Xvfb', ':99', '-screen', '0', '1920x1080x24'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)

from playwright.sync_api import sync_playwright

pw = sync_playwright().start()
browser = pw.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
page = browser.new_page(viewport={'width': 1920, 'height': 1080})

email = 'arthurgabrielcirino02122004@hotmail.com'
passwords = ['02022013L', 'A29b92c10@']

# Step 1: Enter email
page.goto('https://login.live.com/', timeout=20000, wait_until='domcontentloaded')
page.wait_for_selector('input[type=email]', timeout=10000)
page.fill('input[type=email]', email)
page.keyboard.press('Enter')
time.sleep(4)

print(f'After email - URL: {page.url[:120]}')

# Check for "Use password" link
for text in ['Use your password', 'Use sua senha', 'Usar senha', 'Use a password']:
    try:
        link = page.get_by_text(text)
        if link.is_visible(timeout=1500):
            link.click()
            print(f'Clicked: {text}')
            time.sleep(2)
            break
    except:
        continue

# Step 2: Enter password
for pwd in passwords:
    try:
        pwd_input = page.locator('input[type=password]')
        if pwd_input.is_visible(timeout=5000):
            pwd_input.fill(pwd)
            page.keyboard.press('Enter')
            time.sleep(4)
            body = page.inner_text('body').lower()
            if 'incorrect' in body or 'incorreta' in body:
                print(f'Password FAILED: {pwd[:3]}...')
                continue
            print(f'Password OK: {pwd[:3]}...')
            break
    except Exception as e:
        print(f'Password error: {e}')
        continue

# Step 3: Handle post-login
time.sleep(3)
for _ in range(3):
    for sel in ['#idSIButton9', '#idBtn_Back', '#acceptButton']:
        try:
            btn = page.locator(sel)
            if btn.is_visible(timeout=1000):
                btn.click(no_wait_after=True, timeout=3000)
                print(f'Clicked: {sel}')
                time.sleep(2)
                break
        except:
            continue

url = page.url
print(f'\nFinal URL: {url}')

body_text = page.inner_text('body')
print(f'\nBody (first 1000):\n{body_text[:1000]}')

page.screenshot(path='/tmp/ms_verify_debug.png')
print('\nScreenshot: /tmp/ms_verify_debug.png')

masked = re.search(r'(\w{1,10})\*+@(\w[\w.]*)', body_text.lower())
if masked:
    print(f'\nMasked recovery: {masked.group(0)}')

# Check specific states
if 'identity' in url.lower() or 'proofs' in url.lower():
    print('\n=== VERIFICATION PAGE DETECTED ===')
elif 'abuse' in url.lower():
    print('\n=== ABUSE PAGE DETECTED ===')
elif 'outlook.live.com' in url.lower():
    print('\n=== LOGGED IN OK ===')
else:
    print(f'\n=== UNKNOWN STATE: {url} ===')

browser.close()
pw.stop()
