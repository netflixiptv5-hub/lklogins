"""
🔒 CAPTCHA Solver Service — roda na máquina Windows com display real
Baseado no DARKSAGE resolver_pressione_segure()

COMO USAR:
  1. pip install flask undetected-chromedriver selenium
  2. python captcha_service.py
  3. Numa outra janela: ngrok http 5123
  4. Copiar a URL do ngrok (ex: https://abc123.ngrok-free.app)
  5. Setar CAPTCHA_SERVICE_URL no Railway

API:
  POST /solve
    Body: {"email": "...", "password": "...", "job_id": "..."}
    Response: {"solved": true/false, "message": "..."}
  
  GET /health
    Response: {"ok": true, "workers_busy": 0, "workers_max": 3}
"""

from flask import Flask, request, jsonify
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
import time
import random
import os
import tempfile
import uuid
import threading
import traceback

app = Flask(__name__)

# Config
MAX_WORKERS = 3
SENHA_PADRAO = "02022013L"

# Controle de workers
_workers_busy = 0
_workers_lock = threading.Lock()


def log(job_id, msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{job_id}] {msg}")


def _create_driver():
    """Cria Chrome UC — igual ao DARKSAGE."""
    options = uc.ChromeOptions()
    options.add_argument("--window-size=400,350")
    options.add_argument("--window-position=0,0")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--log-level=3")
    options.add_argument("--lang=pt-BR")
    options.add_argument("--disable-http2")

    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "profile.password_manager_leak_detection": False,
        "autofill.profile_enabled": False,
        "profile.default_content_setting_values.notifications": 2,
    }
    options.add_experimental_option("prefs", prefs)

    user_data = os.path.join(tempfile.gettempdir(), f"uc_captcha_{uuid.uuid4().hex[:8]}")
    os.makedirs(user_data, exist_ok=True)
    options.add_argument(f"--user-data-dir={user_data}")

    # Detectar versão do Chrome instalado
    chrome_ver = None
    try:
        import subprocess as _sp
        # Windows
        out = _sp.check_output(
            r'reg query "HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon" /v version',
            shell=True, stderr=_sp.DEVNULL
        ).decode()
        for part in out.strip().split():
            if "." in part and part[0].isdigit():
                chrome_ver = int(part.split(".")[0])
                break
    except:
        pass

    driver = uc.Chrome(options=options, use_subprocess=True, version_main=chrome_ver)

    try:
        driver.execute_cdp_cmd("WebAuthn.enable", {"enableUI": False})
    except:
        pass

    return driver, user_data


def _digitar_lento(element, texto):
    """Digita caractere por caractere como humano."""
    for char in texto:
        element.send_keys(char)
        time.sleep(random.uniform(0.03, 0.08))


def _checar_captcha_resolvido(driver):
    """Checa se o CAPTCHA foi resolvido (conta desbloqueada)."""
    try:
        url = driver.current_url.lower()
        if "abuse" not in url:
            return True
    except:
        pass
    # Checar texto da página — "desbloqueada" / "unlocked" aparece quando resolveu
    try:
        body = driver.find_element(By.TAG_NAME, "body").text.lower()
        if any(t in body for t in [
            "desbloqueada", "unlocked", "has been unlocked",
            "conta foi desbloqueada", "account has been unlocked",
            "continuar", "continue", "atividade recente", "recent activity"
        ]):
            return True
    except:
        pass
    try:
        still = driver.execute_script("""
            var iframes = document.querySelectorAll('iframe');
            for (var i = 0; i < iframes.length; i++) {
                var src = (iframes[i].src || '').toLowerCase();
                if (src.includes('hsprotect') || src.includes('arkose') || src.includes('enforcement')) {
                    var rect = iframes[i].getBoundingClientRect();
                    if (rect.width > 50 && rect.height > 30) return true;
                }
            }
            return false;
        """)
        if not still:
            url = driver.current_url.lower()
            if "abuse" not in url:
                return True
    except:
        pass
    return False


def _resolver_pressione_segure(driver, job_id, max_tentativas=5):
    """Press-and-hold — EXATAMENTE como o DARKSAGE."""
    log(job_id, "CAPTCHA press-and-hold iniciando...")

    for t in range(1, max_tentativas + 1):
        log(job_id, f"  Tentativa {t}/{max_tentativas}")
        try:
            driver.switch_to.default_content()
            time.sleep(1)
            if _checar_captcha_resolvido(driver):
                log(job_id, "  ✓ Já resolvido!")
                return True

            # Achar iframe do CAPTCHA
            captcha_iframe = None
            for iframe in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    src = (iframe.get_attribute("src") or "").lower()
                    rect = iframe.rect
                    if ("hsprotect" in src or "enforcement" in src) and rect['width'] > 50:
                        captcha_iframe = iframe
                        break
                except:
                    pass

            if not captcha_iframe:
                log(job_id, "  Iframe não encontrado, esperando 5s...")
                time.sleep(5)
                if _checar_captcha_resolvido(driver):
                    return True
                continue

            # Scroll pro iframe
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", captcha_iframe)
            time.sleep(0.5)
            iframe_rect = driver.execute_script(
                "var r=arguments[0].getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height};",
                captcha_iframe
            )
            log(job_id, f"  iframe rect: {iframe_rect}")

            # Entrar no iframe pra pegar coordenadas do #px-captcha
            driver.switch_to.frame(captcha_iframe)
            time.sleep(1)
            btn_rect = None
            try:
                px = driver.find_element(By.ID, "px-captcha")
                btn_rect = driver.execute_script(
                    "var r=arguments[0].getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height};", px
                )
                log(job_id, f"  #px-captcha rect: {btn_rect}")
            except:
                log(job_id, "  #px-captcha não encontrado dentro do iframe")
            driver.switch_to.default_content()
            time.sleep(0.3)

            # Calcular offset do clique
            if btn_rect and btn_rect['w'] > 10:
                off_x = int(btn_rect['x'] + btn_rect['w'] / 2 - iframe_rect['w'] / 2)
                off_y = int(btn_rect['y'] + btn_rect['h'] / 2 - iframe_rect['h'] / 2)
            else:
                off_x, off_y = 0, int(iframe_rect['h'] * 0.2)

            # Duração do hold: 14-20s (DARKSAGE style)
            dur = random.uniform(14, 20)
            log(job_id, f"  Hold {dur:.0f}s no offset ({off_x}, {off_y})...")

            # Press and hold com micro-movimentos
            ac = ActionChains(driver)
            ac.move_to_element_with_offset(captcha_iframe, off_x, off_y).pause(0.3).click_and_hold().perform()

            inicio = time.time()
            resolvido = False
            while time.time() - inicio < dur:
                time.sleep(random.uniform(0.5, 1.0))
                try:
                    ActionChains(driver).move_by_offset(
                        random.choice([-1, 0, 1]),
                        random.choice([-1, 0, 1])
                    ).perform()
                except:
                    pass
                try:
                    if "abuse" not in driver.current_url.lower():
                        resolvido = True
                        break
                except:
                    pass

            try:
                ActionChains(driver).release().perform()
            except:
                pass

            elapsed = time.time() - inicio
            log(job_id, f"  Solto após {elapsed:.1f}s")

            if resolvido:
                log(job_id, "  ✓ Resolvido durante hold!")
                return True

            time.sleep(4)
            if _checar_captcha_resolvido(driver):
                log(job_id, "  ✓ Resolvido após release!")
                return True
            time.sleep(random.uniform(2, 4))

        except Exception as e:
            log(job_id, f"  ! Erro: {str(e)[:80]}")
            try:
                driver.switch_to.default_content()
            except:
                pass
            if _checar_captcha_resolvido(driver):
                return True
            time.sleep(2)

    log(job_id, "✗ CAPTCHA falhou após todas tentativas")
    return False


def _solve_abuse(email, password, job_id):
    """Fluxo completo: login → abuse page → Next → CAPTCHA → resolvido."""
    global _workers_busy

    driver = None
    user_data = None
    try:
        log(job_id, f"Iniciando Chrome UC para {email}...")
        driver, user_data = _create_driver()

        # === LOGIN ===
        log(job_id, "Navegando pro login.live.com...")
        driver.get("https://login.live.com/")
        time.sleep(random.uniform(3, 5))

        # Email
        email_input = driver.find_element(By.CSS_SELECTOR, "input[type=email]")
        _digitar_lento(email_input, email)
        time.sleep(0.5)
        try:
            driver.find_element(By.CSS_SELECTOR, "#idSIButton9").click()
        except:
            email_input.send_keys("\n")
        time.sleep(random.uniform(3, 5))

        url_now = driver.current_url.lower()
        log(job_id, f"Após email: {url_now[:80]}")

        # Se já caiu no abuse antes da senha
        if "abuse" not in url_now:
            # Password
            log(job_id, "Digitando senha...")
            try:
                pwd_input = driver.find_element(By.CSS_SELECTOR, "input[type=password]")
            except:
                log(job_id, "Campo de senha não encontrado!")
                return False, "Campo de senha não encontrado"

            _digitar_lento(pwd_input, password)
            time.sleep(0.5)
            try:
                driver.find_element(By.CSS_SELECTOR, "#idSIButton9").click()
            except:
                pwd_input.send_keys("\n")
            time.sleep(random.uniform(4, 6))

            # Stay signed in?
            try:
                stay = driver.find_element(By.CSS_SELECTOR, "#idSIButton9")
                if stay.is_displayed():
                    stay.click()
                    time.sleep(3)
            except:
                pass

        url_now = driver.current_url.lower()
        log(job_id, f"Pós-login URL: {url_now[:80]}")

        if "abuse" not in url_now:
            if "outlook" in url_now or "mail" in url_now:
                log(job_id, "Conta não está em abuse — já desbloqueada!")
                return True, "Conta já desbloqueada"
            log(job_id, f"URL inesperada: {url_now[:100]}")
            return True, "Não é abuse"

        # === ABUSE PAGE — clicar Next ===
        log(job_id, "Na página de abuse, procurando Next...")
        time.sleep(2)

        next_texts = ["next", "próximo", "avançar", "continue", "continuar"]
        clicked_next = False
        
        # Botões
        for btn in driver.find_elements(By.TAG_NAME, "button"):
            try:
                txt = btn.text.lower().strip()
                if btn.is_displayed() and txt in next_texts:
                    btn.click()
                    log(job_id, f"Clicou botão '{txt}'")
                    clicked_next = True
                    break
            except:
                continue

        # Fallback: seletores MS
        if not clicked_next:
            for sel in ["#idSIButton9", "#iNext", "#idBtn_Continue"]:
                try:
                    elem = driver.find_element(By.CSS_SELECTOR, sel)
                    if elem.is_displayed():
                        elem.click()
                        log(job_id, f"Clicou '{sel}'")
                        clicked_next = True
                        break
                except:
                    continue

        if clicked_next:
            time.sleep(random.uniform(6, 10))
        else:
            log(job_id, "Botão Next não encontrado, CAPTCHA pode já estar visível")
            time.sleep(5)

        # === RESOLVER CAPTCHA ===
        solved = _resolver_pressione_segure(driver, job_id, max_tentativas=5)

        if solved:
            log(job_id, "✅ CAPTCHA RESOLVIDO!")
            return True, "Resolvido"
        else:
            log(job_id, "❌ CAPTCHA não resolvido")
            return False, "Falhou após 5 tentativas"

    except Exception as e:
        log(job_id, f"ERRO: {traceback.format_exc()[-300:]}")
        return False, str(e)[:200]

    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
        if user_data:
            try:
                import shutil
                shutil.rmtree(user_data, ignore_errors=True)
            except:
                pass
        with _workers_lock:
            _workers_busy -= 1


# ===================== API ENDPOINTS =====================

@app.route("/health", methods=["GET"])
def health():
    with _workers_lock:
        busy = _workers_busy
    return jsonify({"ok": True, "workers_busy": busy, "workers_max": MAX_WORKERS})


@app.route("/solve", methods=["POST"])
def solve():
    global _workers_busy
    
    data = request.get_json(force=True)
    email = data.get("email", "")
    password = data.get("password", SENHA_PADRAO)
    job_id = data.get("job_id", uuid.uuid4().hex[:8])

    if not email:
        return jsonify({"solved": False, "message": "Email obrigatório"}), 400

    with _workers_lock:
        if _workers_busy >= MAX_WORKERS:
            return jsonify({"solved": False, "message": f"Ocupado ({_workers_busy}/{MAX_WORKERS} workers)"}), 503
        _workers_busy += 1

    log(job_id, f"=== NOVO JOB: {email} ===")
    
    solved, message = _solve_abuse(email, password, job_id)
    
    log(job_id, f"=== RESULTADO: solved={solved}, msg={message} ===")
    return jsonify({"solved": solved, "message": message})


if __name__ == "__main__":
    print("=" * 50)
    print("🔒 CAPTCHA Solver Service")
    print(f"   Workers máx: {MAX_WORKERS}")
    print(f"   Porta: 5123")
    print("=" * 50)
    print()
    print("PRÓXIMO PASSO:")
    print("  1. Abra outro terminal")
    print("  2. Execute: ngrok http 5123")
    print("  3. Copie a URL (ex: https://abc123.ngrok-free.app)")
    print("  4. No Railway, setar variável: CAPTCHA_SERVICE_URL=<url do ngrok>")
    print()
    app.run(host="0.0.0.0", port=5123, threaded=True)
