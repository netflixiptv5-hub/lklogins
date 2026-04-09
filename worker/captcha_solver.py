"""
PerimeterX "Press and Hold" CAPTCHA Solver.
Uses undetected-chromedriver (Selenium) since Playwright's Chromium fails PX fingerprinting.
After solving, returns so the main Playwright flow can continue.

Also includes a Playwright-based solver as a faster first attempt.

CHANGELOG:
- Adicionado job_id em todas as funções
- Logs integrados com job_logger (aparecem em /api/logs/:jobId)
- Logging detalhado em CADA etapa (URL, iframes, botões, page source snippets)
- Melhorada detecção de iframe CAPTCHA (mais seletores)
- Melhorada detecção de botão Next na abuse intro
- Mais tempo de espera pro iframe no Playwright
"""

import time
import random
import logging
import os
import subprocess

logger = logging.getLogger("CAPTCHA")

# Tenta importar job_logger - se falhar, fallback pra logging normal
try:
    from job_logger import log as jlog
except ImportError:
    jlog = None


def _log(job_id: str, message: str, level: str = "info"):
    """Log tanto no logger padrão quanto no job_logger."""
    tag = f"[{job_id}] CAPTCHA: {message}" if job_id else f"CAPTCHA: {message}"
    
    if level == "error":
        logger.error(tag)
    elif level == "warning":
        logger.warning(tag)
    else:
        logger.info(tag)
    
    # Salvar no job_logger (aparece em /api/logs/:jobId)
    if jlog and job_id:
        try:
            jlog(job_id, f"CAPTCHA: {message}", level)
        except:
            pass


def _ensure_display():
    """Ensure Xvfb is running."""
    display = os.environ.get("DISPLAY", "")
    if not display:
        os.environ["DISPLAY"] = ":99"
    try:
        result = subprocess.run(["pgrep", "-f", "Xvfb"], capture_output=True, timeout=3)
        if result.returncode != 0:
            subprocess.Popen(
                ["Xvfb", ":99", "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            time.sleep(1)
    except:
        pass


def _get_chrome_version():
    """Detect installed Chrome major version."""
    try:
        out = subprocess.check_output(
            ["google-chrome", "--version"], stderr=subprocess.DEVNULL
        ).decode().strip()
        return int(out.split()[-1].split(".")[0])
    except:
        return None


def _check_abuse_solved(driver):
    """Check if we're past the abuse page."""
    try:
        url = driver.current_url.lower()
        if "abuse" not in url:
            return True
    except:
        pass
    try:
        still_visible = driver.execute_script("""
            var iframes = document.querySelectorAll('iframe');
            for (var i = 0; i < iframes.length; i++) {
                var src = (iframes[i].src || '').toLowerCase();
                if (src.includes('captcha') || src.includes('hsprotect') || src.includes('arkose') || 
                    src.includes('enforcement') || src.includes('perimeterx') || src.includes('px-cdn')) {
                    var rect = iframes[i].getBoundingClientRect();
                    if (rect.width > 50 && rect.height > 30) return true;
                }
            }
            return false;
        """)
        if not still_visible:
            url = driver.current_url.lower()
            if "abuse" not in url:
                return True
    except:
        pass
    return False


def _find_captcha_iframe(driver, job_id):
    """Find the CAPTCHA iframe using multiple strategies."""
    from selenium.webdriver.common.by import By
    
    # Strategy 1: Buscar por src conhecido
    known_srcs = ['hsprotect', 'enforcement', 'arkose', 'captcha', 'perimeterx', 'px-cdn', 'px-cloud']
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    _log(job_id, f"Encontrados {len(iframes)} iframes na página")
    
    for i, iframe in enumerate(iframes):
        try:
            src = (iframe.get_attribute("src") or "").lower()
            rect = iframe.rect
            _log(job_id, f"  iframe[{i}]: src={src[:120]}, size={rect.get('width',0)}x{rect.get('height',0)}")
            
            # Verificar se é um iframe de CAPTCHA
            is_captcha = any(k in src for k in known_srcs)
            # Também verificar iframes sem src mas com tamanho razoável (PX pode injetar via JS)
            is_px_candidate = (not src or src == "about:blank") and rect.get('width', 0) > 200 and rect.get('height', 0) > 100
            
            if is_captcha and rect.get('width', 0) > 50:
                _log(job_id, f"  → CAPTCHA iframe encontrado via src match!")
                return iframe
            if is_px_candidate:
                # Verificar se tem #px-captcha dentro
                try:
                    driver.switch_to.frame(iframe)
                    px = driver.find_elements(By.ID, "px-captcha")
                    driver.switch_to.default_content()
                    if px:
                        _log(job_id, f"  → CAPTCHA iframe encontrado via #px-captcha check (iframe sem src)!")
                        return iframe
                except:
                    driver.switch_to.default_content()
        except Exception as e:
            _log(job_id, f"  iframe[{i}]: erro ao inspecionar: {str(e)[:80]}")
            continue
    
    # Strategy 2: Buscar por div que pode conter o CAPTCHA
    try:
        page_source_snippet = driver.page_source[:3000].lower()
        if "px-captcha" in page_source_snippet:
            _log(job_id, "px-captcha encontrado no page_source, mas não em iframe. Pode estar inline.")
            # Tentar achar #px-captcha diretamente na página
            try:
                px_direct = driver.find_element(By.ID, "px-captcha")
                if px_direct:
                    _log(job_id, "  → #px-captcha está diretamente na página (sem iframe)!")
                    return "INLINE"
            except:
                pass
        else:
            _log(job_id, f"px-captcha NÃO encontrado no page_source (primeiros 3000 chars)")
    except Exception as e:
        _log(job_id, f"Erro ao checar page_source: {str(e)[:80]}")
    
    return None


def _find_and_click_next(driver, job_id):
    """Find and click the Next/Próximo button on the abuse intro page."""
    from selenium.webdriver.common.by import By
    
    _log(job_id, "Procurando botão Next/Próximo na página de abuse...")
    
    # Logar o conteúdo da página pra debug
    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text[:500]
        _log(job_id, f"Body text: {body_text[:300]}")
    except:
        pass
    
    # Strategy 1: Botões com texto
    next_texts = ["next", "próximo", "siguiente", "avançar", "continue", "continuar", "verify", "verificar"]
    
    try:
        buttons = driver.find_elements(By.TAG_NAME, "button")
        _log(job_id, f"Encontrados {len(buttons)} botões")
        for btn in buttons:
            try:
                txt = btn.text.lower().strip()
                val = (btn.get_attribute("value") or "").lower().strip()
                btn_id = btn.get_attribute("id") or ""
                _log(job_id, f"  button: text='{txt}', value='{val}', id='{btn_id}', visible={btn.is_displayed()}")
                if btn.is_displayed() and (txt in next_texts or val in next_texts):
                    btn.click()
                    _log(job_id, f"  → Clicou no botão '{txt or val}'!")
                    return True
            except:
                continue
    except:
        pass
    
    # Strategy 2: input[type=submit]
    try:
        submits = driver.find_elements(By.CSS_SELECTOR, "input[type=submit], input[type=button]")
        _log(job_id, f"Encontrados {len(submits)} inputs submit/button")
        for s in submits:
            try:
                val = (s.get_attribute("value") or "").lower().strip()
                s_id = s.get_attribute("id") or ""
                _log(job_id, f"  input: value='{val}', id='{s_id}', visible={s.is_displayed()}")
                if s.is_displayed() and (val in next_texts or s_id in ["idSIButton9", "iNext"]):
                    s.click()
                    _log(job_id, f"  → Clicou no input '{val or s_id}'!")
                    return True
            except:
                continue
    except:
        pass
    
    # Strategy 3: Links com texto Next
    try:
        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            try:
                txt = link.text.lower().strip()
                if link.is_displayed() and txt in next_texts:
                    link.click()
                    _log(job_id, f"  → Clicou no link '{txt}'!")
                    return True
            except:
                continue
    except:
        pass
    
    # Strategy 4: Qualquer elemento clicável com ID conhecido da Microsoft
    for sel in ["#idSIButton9", "#iNext", "#idBtn_Continue", "#idSubmit_ProofConfirm", 
                 ".win-button.button_primary", "button.primary", "[data-testid='primaryButton']"]:
        try:
            elem = driver.find_element(By.CSS_SELECTOR, sel)
            if elem.is_displayed():
                elem.click()
                _log(job_id, f"  → Clicou via selector '{sel}'!")
                return True
        except:
            continue
    
    _log(job_id, "Nenhum botão Next encontrado!", "warning")
    
    # Logar HTML completo da página pra debug
    try:
        html = driver.page_source[:5000]
        _log(job_id, f"Page HTML (first 2000): {html[:2000]}")
    except:
        pass
    
    return False


def _do_press_and_hold_inline(driver, job_id, attempt_num):
    """Press and hold diretamente no #px-captcha (sem iframe)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains
    
    try:
        px = driver.find_element(By.ID, "px-captcha")
        rect = driver.execute_script(
            "var r=arguments[0].getBoundingClientRect();"
            "return{x:r.x,y:r.y,w:r.width,h:r.height};", px
        )
        _log(job_id, f"px-captcha inline rect: {rect}")
        
        # Scroll into view
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", px)
        time.sleep(0.5)
        
        if attempt_num <= 2:
            hold_duration = random.uniform(14, 18)
        else:
            hold_duration = random.uniform(18, 24)
        
        _log(job_id, f"Hold inline #px-captcha for {hold_duration:.1f}s [attempt {attempt_num}]")
        
        ac = ActionChains(driver)
        ac.move_to_element(px).pause(random.uniform(0.2, 0.5)).click_and_hold().perform()
        
        start = time.time()
        solved = False
        while time.time() - start < hold_duration:
            time.sleep(random.uniform(0.4, 0.9))
            try:
                ActionChains(driver).move_by_offset(
                    random.choice([-2, -1, 0, 1, 2]),
                    random.choice([-1, 0, 1])
                ).perform()
            except:
                pass
            try:
                if "abuse" not in driver.current_url.lower():
                    solved = True
                    break
            except:
                pass
        
        try:
            ActionChains(driver).release().perform()
        except:
            pass
        
        elapsed = time.time() - start
        _log(job_id, f"Released inline after {elapsed:.1f}s, solved={solved}")
        return solved
        
    except Exception as e:
        _log(job_id, f"Erro press_and_hold inline: {str(e)[:150]}", "error")
        return False


def _do_press_and_hold(driver, captcha_iframe, attempt_num, job_id=""):
    """Execute the press-and-hold action on the captcha iframe."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    # Scroll iframe into view
    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'});", captcha_iframe
    )
    time.sleep(0.5)

    # Get iframe bounding rect
    iframe_rect = driver.execute_script(
        "var r=arguments[0].getBoundingClientRect();"
        "return{x:r.x,y:r.y,w:r.width,h:r.height};",
        captcha_iframe
    )
    _log(job_id, f"iframe rect: {iframe_rect}")

    # Switch into iframe to find the #px-captcha button
    driver.switch_to.frame(captcha_iframe)
    time.sleep(0.5)
    btn_rect = None
    try:
        px = driver.find_element(By.ID, "px-captcha")
        btn_rect = driver.execute_script(
            "var r=arguments[0].getBoundingClientRect();"
            "return{x:r.x,y:r.y,w:r.width,h:r.height};",
            px
        )
        _log(job_id, f"#px-captcha rect dentro do iframe: {btn_rect}")
    except Exception as e:
        _log(job_id, f"#px-captcha NÃO encontrado dentro do iframe: {str(e)[:100]}", "warning")
        # Logar conteúdo do iframe
        try:
            iframe_html = driver.page_source[:1500]
            _log(job_id, f"iframe HTML: {iframe_html[:800]}")
        except:
            pass
    
    driver.switch_to.default_content()
    time.sleep(0.3)

    # Calculate click offset relative to iframe center
    if btn_rect and btn_rect.get('w', 0) > 10:
        off_x = int(btn_rect['x'] + btn_rect['w'] / 2 - iframe_rect['w'] / 2)
        off_y = int(btn_rect['y'] + btn_rect['h'] / 2 - iframe_rect['h'] / 2)
    else:
        off_x = 0
        off_y = int(iframe_rect['h'] * 0.2)

    # Vary hold duration
    if attempt_num <= 2:
        hold_duration = random.uniform(14, 18)
    else:
        hold_duration = random.uniform(18, 24)

    _log(job_id, f"Hold at offset ({off_x}, {off_y}) for {hold_duration:.1f}s [attempt {attempt_num}]")

    # Press and hold with micro-movements
    ac = ActionChains(driver)
    ac.move_to_element_with_offset(
        captcha_iframe, off_x, off_y
    ).pause(random.uniform(0.2, 0.5)).click_and_hold().perform()

    start = time.time()
    solved = False
    while time.time() - start < hold_duration:
        time.sleep(random.uniform(0.4, 0.9))
        try:
            ActionChains(driver).move_by_offset(
                random.choice([-2, -1, 0, 1, 2]),
                random.choice([-1, 0, 1])
            ).perform()
        except:
            pass
        try:
            if "abuse" not in driver.current_url.lower():
                solved = True
                break
        except:
            pass

    try:
        ActionChains(driver).release().perform()
    except:
        pass

    elapsed = time.time() - start
    _log(job_id, f"Released after {elapsed:.1f}s, solved_during_hold={solved}")
    return solved


def solve_captcha_with_uc(email: str, password: str, max_attempts: int = 5, job_id: str = "", abuse_url: str = "") -> bool:
    """
    Solve the PerimeterX CAPTCHA using undetected-chromedriver.
    
    If abuse_url is provided, navigates directly to it (skips login).
    Otherwise, logs into the account and handles the Abuse page.
    
    Returns True if account was unlocked, False if failed.
    """
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    _ensure_display()

    chrome_version = _get_chrome_version()
    _log(job_id, f"Chrome version: {chrome_version}")

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=pt-BR")
    # Extra anti-detection
    options.add_argument("--disable-features=IsolateOrigins,site-per-process")

    driver = None
    try:
        uc_kwargs = {"options": options}
        if chrome_version:
            uc_kwargs["version_main"] = chrome_version

        _log(job_id, "Starting UC Chrome...")
        driver = uc.Chrome(**uc_kwargs)
        driver.set_page_load_timeout(45)

        # === Step 1: Login ===
        _log(job_id, f"UC: Navigating to login... email={email}")
        driver.get("https://login.live.com/")
        time.sleep(random.uniform(2, 4))

        _log(job_id, f"UC: Login page URL: {driver.current_url}")

        # Email
        try:
            email_input = driver.find_element(By.CSS_SELECTOR, "input[type=email]")
        except:
            _log(job_id, f"UC: No email input found. URL: {driver.current_url}", "warning")
            return False
        
        for char in email:
            email_input.send_keys(char)
            time.sleep(random.uniform(0.03, 0.08))
        time.sleep(0.5)

        try:
            driver.find_element(By.CSS_SELECTOR, "#idSIButton9").click()
        except:
            email_input.send_keys("\n")
        time.sleep(random.uniform(3, 5))

        _log(job_id, f"UC: After email submit, URL: {driver.current_url}")

        # Check if we hit abuse even before password
        url_now = driver.current_url.lower()
        if "abuse" in url_now:
            _log(job_id, "UC: Bloqueado ANTES do password! Indo direto pro CAPTCHA...")
        else:
            # Password
            _log(job_id, "UC: Entering password...")
            try:
                pwd_input = driver.find_element(By.CSS_SELECTOR, "input[type=password]")
            except:
                _log(job_id, f"UC: No password field found. URL: {driver.current_url}", "warning")
                try:
                    body_text = driver.find_element(By.TAG_NAME, "body").text[:500]
                    _log(job_id, f"UC: Body text: {body_text[:300]}", "warning")
                except:
                    pass
                # If we're at identity verification, this UC attempt won't work
                if "identity" in url_now or "proofs" in url_now or "verify" in url_now:
                    _log(job_id, "UC: Hit identity verification — UC can't solve this, returning False", "warning")
                return False
            
            for char in password:
                pwd_input.send_keys(char)
                time.sleep(random.uniform(0.03, 0.08))
            time.sleep(0.5)

            try:
                driver.find_element(By.CSS_SELECTOR, "#idSIButton9").click()
            except:
                pwd_input.send_keys("\n")
            time.sleep(random.uniform(4, 6))

            # Handle "Stay signed in?" 
            try:
                stay = driver.find_element(By.CSS_SELECTOR, "#idSIButton9")
                if stay.is_displayed():
                    stay.click()
                    time.sleep(3)
            except:
                pass

        url = driver.current_url.lower()
        _log(job_id, f"UC: Post-login URL: {driver.current_url}")

        # If not on abuse page, check what happened
        if "abuse" not in url:
            if "outlook" in url or "mail" in url:
                _log(job_id, "UC: No abuse page — account already unlocked!")
                return True
            if "identity" in url or "proofs" in url:
                _log(job_id, "UC: Hit identity verification instead of abuse — can't proceed", "warning")
                return False
            _log(job_id, f"UC: Unexpected URL after login: {url}", "warning")
            # Could still be resolved, return True if not abuse
            return True

        # === Step 2: Handle the abuse intro page ===
        _log(job_id, "UC: On abuse page, handling intro...")
        time.sleep(2)
        
        # Try clicking Next/Próximo
        clicked_next = _find_and_click_next(driver, job_id)

        if clicked_next:
            _log(job_id, "UC: Clicked Next, waiting for CAPTCHA to load...")
            time.sleep(random.uniform(5, 8))
        else:
            _log(job_id, "UC: No Next button found, CAPTCHA may already be visible or page layout changed")
            time.sleep(3)

        _log(job_id, f"UC: Current URL after Next: {driver.current_url}")

        # === Step 3: Solve CAPTCHA ===
        for attempt in range(1, max_attempts + 1):
            _log(job_id, f"UC: CAPTCHA attempt {attempt}/{max_attempts}")

            if _check_abuse_solved(driver):
                _log(job_id, "UC: ✓ CAPTCHA already solved!")
                return True

            # Find the captcha iframe
            captcha_target = _find_captcha_iframe(driver, job_id)

            if captcha_target is None:
                _log(job_id, f"UC: No CAPTCHA found, waiting 8s... URL: {driver.current_url}")
                time.sleep(8)
                if _check_abuse_solved(driver):
                    _log(job_id, "UC: ✓ Solved while waiting!")
                    return True
                
                # Tentar clicar Next de novo (pode ser que a página carregou)
                if attempt <= 2:
                    _log(job_id, "UC: Tentando clicar Next novamente...")
                    if _find_and_click_next(driver, job_id):
                        time.sleep(5)
                continue

            # Execute press and hold
            if captcha_target == "INLINE":
                solved_during_hold = _do_press_and_hold_inline(driver, job_id, attempt)
            else:
                solved_during_hold = _do_press_and_hold(driver, captcha_target, attempt, job_id)

            if solved_during_hold:
                _log(job_id, "UC: ✓ Solved during hold!")
                return True

            # Wait for the page to settle after release
            _log(job_id, "UC: Waiting for page to settle after release...")
            settled = False
            for wait_i in range(12):  # Up to 60 seconds
                time.sleep(5)
                
                url = driver.current_url.lower()
                if "abuse" not in url:
                    _log(job_id, f"UC: ✓ Solved after {(wait_i + 1) * 5}s wait!")
                    return True

                try:
                    body = driver.find_element(By.TAG_NAME, "body").text.lower()
                except:
                    body = ""

                if any(t in body for t in ["press and hold", "try again", "pressione e segure", "tente novamente"]):
                    _log(job_id, f"UC: 'Try again' detected after {(wait_i + 1) * 5}s, will retry")
                    settled = True
                    break

                if "loading" in body or body.strip() == "":
                    continue
                    
                # Se tem conteúdo mas não mudou, pode ter falhado silenciosamente
                if wait_i >= 6:
                    _log(job_id, f"UC: Waited {(wait_i + 1) * 5}s sem mudança, breaking...")
                    settled = True
                    break

            time.sleep(random.uniform(2, 5))

        _log(job_id, "UC: ✗ CAPTCHA failed after all attempts", "error")
        return False

    except Exception as e:
        _log(job_id, f"UC: Error: {str(e)[:300]}", "error")
        import traceback
        _log(job_id, f"UC: Traceback: {traceback.format_exc()[-500:]}", "error")
        return False

    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass


# ==================== PLAYWRIGHT-BASED SOLVER ====================

def _find_accessibility_button(page, frame_locator, iframe_handle, job_id):
    """
    Find the accessibility icon button inside the CAPTCHA iframe.
    
    O botão de acessibilidade do PerimeterX é um pequeno ícone (boneco azul)
    que fica ao lado esquerdo do botão "Pressione e segure" (#px-captcha).
    Está DENTRO do iframe.
    """
    # === STRATEGY 1: Buscar dentro do iframe via frame_locator ===
    if frame_locator is not None:
        # Seletores conhecidos do botão de acessibilidade do PX
        frame_selectors = [
            "#px-captcha-accessibility",
            "[aria-label*='ccessib']",  # accessibility / acessibilidade
            "[aria-label*='Accessible']",
            ".accessibility-icon",
            ".px-accessibility",
            "button.accessibility",
            # PX coloca o ícone como irmão do #px-captcha
            "#px-captcha ~ button",
            "#px-captcha ~ div[role='button']",
            "#px-captcha ~ a",
            "#px-captcha ~ div > button",
            # SVG de acessibilidade
            "svg[aria-label*='ccessib']",
            "img[alt*='ccessib']",
            # Genérico: qualquer botão que não é o px-captcha
            "button:not(#px-captcha)",
            "div[role='button']:not(#px-captcha)",
            "a:not([href=''])",
        ]
        
        for sel in frame_selectors:
            try:
                elem = frame_locator.locator(sel).first
                if elem.is_visible(timeout=2000):
                    box = elem.bounding_box()
                    # O botão de acessibilidade é pequeno (< 80px wide) e fica à esquerda do px-captcha
                    if box and box['width'] < 120 and box['height'] < 120:
                        _log(job_id, f"PW: Accessibility found in iframe via '{sel}' box={box}")
                        return elem, "frame"
                    else:
                        _log(job_id, f"PW: '{sel}' visible but too big ({box}), skipping")
            except:
                continue
        
        # Log iframe content for debugging
        try:
            # Pegar o HTML do iframe pra entender a estrutura
            iframe_html = frame_locator.locator("body").inner_html(timeout=3000)
            _log(job_id, f"PW: iframe HTML (500): {iframe_html[:500]}")
        except Exception as e:
            _log(job_id, f"PW: Couldn't read iframe HTML: {str(e)[:80]}")
    
    # === STRATEGY 2: Buscar via page.frames() (acessa os frames reais) ===
    try:
        for frame_obj in page.frames:
            frame_url = frame_obj.url.lower()
            if any(k in frame_url for k in ['hsprotect', 'enforcement', 'captcha', 'perimeterx', 'px-cdn']):
                _log(job_id, f"PW: Scanning real frame: {frame_url[:80]}")
                
                # Listar TODOS os elementos visíveis no frame
                try:
                    all_els = frame_obj.query_selector_all("*")
                    visible_count = 0
                    for el in all_els:
                        try:
                            box = el.bounding_box()
                            if box and box['width'] > 5 and box['height'] > 5:
                                visible_count += 1
                                tag = el.evaluate("el => el.tagName")
                                eid = el.evaluate("el => el.id || ''")
                                cls = el.evaluate("el => (el.className || '').toString().substring(0, 60)")
                                aria = el.evaluate("el => el.getAttribute('aria-label') || ''")
                                
                                if visible_count <= 15:  # Log first 15 visible elements
                                    _log(job_id, f"  frame el: <{tag}> id={eid} class={cls[:40]} aria={aria[:30]} size={box['width']:.0f}x{box['height']:.0f}")
                                
                                # Detectar botão de acessibilidade:
                                # - Não é o #px-captcha
                                # - É pequeno (ícone)
                                # - Está perto do px-captcha
                                is_acc = False
                                if 'ccessib' in aria.lower() or 'ccessib' in cls.lower():
                                    is_acc = True
                                elif eid != 'px-captcha' and tag in ['BUTTON', 'A', 'DIV'] and box['width'] < 80 and box['height'] < 80 and box['width'] > 15:
                                    # Pequeno e clicável — provável botão de acessibilidade
                                    is_acc = True
                                
                                if is_acc:
                                    _log(job_id, f"PW: → ACCESSIBILITY BUTTON via frame scan! <{tag}> id={eid} size={box['width']:.0f}x{box['height']:.0f}")
                                    # Converter ElementHandle pra Locator-like que podemos clicar
                                    return el, "element_handle"
                        except:
                            continue
                    
                    _log(job_id, f"PW: {visible_count} visible elements in frame, no accessibility button found")
                except Exception as e:
                    _log(job_id, f"PW: Error scanning frame: {str(e)[:100]}")
    except Exception as e:
        _log(job_id, f"PW: Error iterating page.frames: {str(e)[:100]}")
    
    # === STRATEGY 3: Scan the MAIN PAGE for small clickable elements near #px-captcha ===
    # O botão de acessibilidade do PX fica na PÁGINA PRINCIPAL, ao lado do iframe/div do captcha
    try:
        _log(job_id, "PW: Scanning main page for accessibility button near captcha...")
        
        # Primeiro, pegar a posição do #px-captcha na página (ou do iframe)
        captcha_y = None
        try:
            px_main = page.locator("#px-captcha").first
            if px_main.is_visible(timeout=2000):
                px_box = px_main.bounding_box()
                if px_box:
                    captcha_y = px_box['y']
                    _log(job_id, f"PW: #px-captcha on main page at y={captcha_y:.0f}")
        except:
            pass
        
        # Listar TODOS os elementos clicáveis pequenos na página
        all_elements = page.query_selector_all("button, a, [role='button'], div[onclick], span[onclick], img[onclick], svg, [tabindex='0']")
        _log(job_id, f"PW: {len(all_elements)} clickable elements on main page")
        
        for el in all_elements:
            try:
                box = el.bounding_box()
                if not box or box['width'] < 10 or box['height'] < 10:
                    continue
                if box['width'] > 100 or box['height'] > 100:
                    continue  # Muito grande pra ser ícone de acessibilidade
                
                eid = el.evaluate("el => el.id || ''")
                tag = el.evaluate("el => el.tagName")
                cls = el.evaluate("el => (el.className || '').toString().substring(0, 80)")
                aria = el.evaluate("el => el.getAttribute('aria-label') || ''")
                title = el.evaluate("el => el.getAttribute('title') || ''")
                
                _log(job_id, f"  page el: <{tag}> id={eid} class={cls[:40]} aria={aria[:30]} title={title[:30]} box=({box['x']:.0f},{box['y']:.0f}) size={box['width']:.0f}x{box['height']:.0f}")
                
                # Detectar se é o botão de acessibilidade:
                # - Está perto do captcha (mesma região Y)
                # - É pequeno (ícone ~30-50px)
                # - Tem referência a accessibility/acessibilidade
                is_near_captcha = captcha_y is not None and abs(box['y'] - captcha_y) < 80
                has_acc_hint = any(k in (aria + cls + title + eid).lower() for k in ['ccessib', 'a11y', 'wheelchair', 'human', 'handicap'])
                is_small_icon = box['width'] < 60 and box['height'] < 60 and box['width'] > 12
                is_not_captcha = eid != 'px-captcha'
                
                if is_not_captcha and (has_acc_hint or (is_near_captcha and is_small_icon)):
                    _log(job_id, f"PW: → ACCESSIBILITY BUTTON on main page! <{tag}> id={eid} near_captcha={is_near_captcha} acc_hint={has_acc_hint}")
                    return el, "element_handle"
            except:
                continue
    except Exception as e:
        _log(job_id, f"PW: Error scanning main page: {str(e)[:100]}")
    
    _log(job_id, "PW: Accessibility button NOT found anywhere", "warning")
    return None, None


def _try_accessible_challenge(page, frame_locator, iframe_handle, job_id):
    """
    Try the accessible challenge flow:
    1. Click accessibility icon
    2. Wait for bar to auto-fill
    3. Click when it says "Clique novamente" / "Click again"
    
    Returns True if solved.
    """
    _log(job_id, "PW: Trying ACCESSIBLE challenge flow...")
    
    # Step 1: Find and click accessibility button
    acc_btn, location = _find_accessibility_button(page, frame_locator, iframe_handle, job_id)
    
    if not acc_btn:
        return False
    
    # Click the accessibility button
    try:
        if location == "element_handle":
            # ElementHandle from page.frames scan
            box = acc_btn.bounding_box()
            if box:
                # Clicar via mouse.click nas coordenadas (mais confiável pra ElementHandle)
                page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                _log(job_id, f"PW: Clicked accessibility via coords ({box['x'] + box['width']/2:.0f}, {box['y'] + box['height']/2:.0f})")
            else:
                acc_btn.click()
                _log(job_id, "PW: Clicked accessibility ElementHandle directly")
        elif location == "frame":
            # FrameLocator element
            try:
                acc_btn.click(timeout=5000)
                _log(job_id, "PW: Clicked accessibility in frame!")
            except:
                box = acc_btn.bounding_box()
                if box:
                    page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                    _log(job_id, f"PW: Clicked accessibility via coords fallback")
                else:
                    _log(job_id, "PW: Could not click accessibility button", "warning")
                    return False
        else:
            acc_btn.click(timeout=5000)
            _log(job_id, "PW: Clicked accessibility button!")
    except Exception as e:
        _log(job_id, f"PW: Failed to click accessibility: {str(e)[:100]}", "warning")
        return False
    
    time.sleep(2)
    
    # Step 2: Wait for the bar to auto-fill (up to 30s)
    _log(job_id, "PW: Waiting for accessible bar to fill...")
    
    # Helper to get px-captcha text (try multiple methods)
    def _get_px_text():
        # Method 1: via frame_locator
        if frame_locator:
            try:
                return frame_locator.locator("#px-captcha").inner_text(timeout=1000)
            except:
                pass
        # Method 2: via page.frames
        try:
            for f in page.frames:
                fu = f.url.lower()
                if any(k in fu for k in ['hsprotect', 'enforcement', 'captcha', 'perimeterx']):
                    el = f.query_selector("#px-captcha")
                    if el:
                        return el.inner_text()
        except:
            pass
        # Method 3: inline
        try:
            return page.locator("#px-captcha").inner_text(timeout=500)
        except:
            pass
        return ""
    
    for wait_i in range(60):  # Check every 0.5s, up to 30s
        time.sleep(0.5)
        
        # Check if already solved (URL changed)
        try:
            if "abuse" not in page.url.lower():
                _log(job_id, f"PW: ✓ Solved during accessible wait! ({(wait_i+1)*0.5:.0f}s)")
                return True
        except:
            pass
        
        # Check for "Click again" / "Clique novamente" text
        px_text = _get_px_text()
        px_text_lower = px_text.lower().strip()
        
        if px_text_lower and any(t in px_text_lower for t in ["click", "clique", "tap", "toque", "again", "novamente"]):
            _log(job_id, f"PW: Bar filled! Text: '{px_text}' — clicking now!")
            
            # Step 3: Click the button
            clicked = False
            # Try via frame_locator
            if frame_locator:
                try:
                    frame_locator.locator("#px-captcha").click(timeout=5000)
                    _log(job_id, "PW: Clicked #px-captcha via frame_locator!")
                    clicked = True
                except:
                    pass
            # Try via page.frames
            if not clicked:
                try:
                    for f in page.frames:
                        fu = f.url.lower()
                        if any(k in fu for k in ['hsprotect', 'enforcement', 'captcha', 'perimeterx']):
                            el = f.query_selector("#px-captcha")
                            if el:
                                box = el.bounding_box()
                                if box:
                                    page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                                    _log(job_id, "PW: Clicked #px-captcha via frame coords!")
                                    clicked = True
                                    break
                except:
                    pass
            # Try inline
            if not clicked:
                try:
                    page.locator("#px-captcha").click(timeout=3000)
                    _log(job_id, "PW: Clicked #px-captcha inline!")
                    clicked = True
                except:
                    pass
            
            if not clicked:
                _log(job_id, "PW: Could not click #px-captcha after fill!", "warning")
            
            # Wait for solve
            for solve_wait in range(20):
                time.sleep(2)
                try:
                    if "abuse" not in page.url.lower():
                        _log(job_id, f"PW: ✓ Accessible challenge SOLVED! ({solve_wait*2}s after click)")
                        return True
                except:
                    pass
            
            _log(job_id, "PW: Clicked but still on abuse page...", "warning")
            return False
        
        # Log progress
        if wait_i % 10 == 9:
            _log(job_id, f"PW: Still waiting for bar to fill... ({(wait_i+1)*0.5:.0f}s) text='{px_text_lower[:50]}'")
    
    _log(job_id, "PW: Accessible bar didn't fill in 30s", "warning")
    return False


def solve_captcha_playwright(page, max_attempts: int = 4, job_id: str = "") -> bool:
    """
    Try to solve PerimeterX CAPTCHA directly in Playwright.
    
    Strategy order:
    1. ACCESSIBLE CHALLENGE (click icon → wait bar fill → click again) — PREFERRED
    2. CDP press-and-hold as fallback
    """
    _log(job_id, "PW: Attempting Playwright CAPTCHA solve...")
    _log(job_id, f"PW: Current URL: {page.url}")

    for attempt in range(1, max_attempts + 1):
        _log(job_id, f"PW: Attempt {attempt}/{max_attempts}")

        # Check if already solved
        try:
            url = page.url.lower()
            if "abuse" not in url:
                _log(job_id, "PW: ✓ Already solved!")
                return True
        except:
            pass

        # Log page content for debug
        if attempt == 1:
            try:
                body = page.inner_text("body")[:500]
                _log(job_id, f"PW: Body text: {body[:300]}")
            except:
                pass

        # Try clicking Next button first (abuse intro page)
        if attempt <= 2:
            try:
                for text in ["Next", "Próximo", "Continue", "Continuar", "Avançar"]:
                    btn = page.get_by_role("button", name=text)
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        _log(job_id, f"PW: Clicked '{text}' button")
                        time.sleep(4)
                        break
            except:
                pass
            # Also try #idSIButton9
            try:
                nxt = page.locator("#idSIButton9, #iNext")
                if nxt.is_visible(timeout=1000):
                    nxt.click()
                    _log(job_id, "PW: Clicked #idSIButton9/#iNext")
                    time.sleep(4)
            except:
                pass

        # Find captcha iframe - buscar com mais seletores e mais tempo
        try:
            iframe_handle = None
            iframe_selectors = [
                "iframe[src*='hsprotect']",
                "iframe[src*='enforcement']",
                "iframe[src*='arkose']",
                "iframe[src*='captcha']",
                "iframe[src*='perimeterx']",
                "iframe[src*='px-cdn']",
                "iframe[src*='px-cloud']",
            ]
            
            # Dar mais tempo pro iframe carregar (era 3s, agora 8s)
            wait_start = time.time()
            while time.time() - wait_start < 10:
                for selector in iframe_selectors:
                    try:
                        loc = page.locator(selector).first
                        if loc.is_visible(timeout=1000):
                            iframe_handle = loc
                            _log(job_id, f"PW: CAPTCHA iframe found via '{selector}'")
                            break
                    except:
                        continue
                if iframe_handle:
                    break
                
                # Tentar achar #px-captcha diretamente (pode não estar em iframe)
                try:
                    px_direct = page.locator("#px-captcha")
                    if px_direct.is_visible(timeout=1000):
                        _log(job_id, "PW: #px-captcha encontrado INLINE (sem iframe)")
                        iframe_handle = "INLINE"
                        break
                except:
                    pass
                
                time.sleep(2)

            if not iframe_handle:
                # Log all iframes for debug
                try:
                    iframe_count = page.locator("iframe").count()
                    _log(job_id, f"PW: {iframe_count} iframes na página, nenhum match")
                    for i in range(min(iframe_count, 5)):
                        src = page.locator("iframe").nth(i).get_attribute("src") or ""
                        _log(job_id, f"  PW iframe[{i}]: src={src[:120]}")
                except:
                    pass
                _log(job_id, "PW: No captcha iframe found after 10s")
                continue

            # === RESOLVE FRAME REFERENCE ===
            frame = None
            cx, cy = None, None
            
            if iframe_handle == "INLINE":
                px_btn = page.locator("#px-captcha")
                btn_box = px_btn.bounding_box()
                if not btn_box:
                    _log(job_id, "PW: #px-captcha bounding box is None")
                    continue
                cx = btn_box['x'] + btn_box['width'] / 2
                cy = btn_box['y'] + btn_box['height'] / 2
            else:
                iframe_box = iframe_handle.bounding_box()
                if not iframe_box or iframe_box['width'] < 50:
                    _log(job_id, f"PW: Iframe too small or invisible: {iframe_box}")
                    continue

                frame_selector = ", ".join(iframe_selectors)
                frame = page.frame_locator(frame_selector).first
                px_btn = frame.locator("#px-captcha")
                
                try:
                    btn_box = px_btn.bounding_box(timeout=5000)
                except:
                    btn_box = None

                if btn_box and btn_box['width'] > 10:
                    cx = btn_box['x'] + btn_box['width'] / 2
                    cy = btn_box['y'] + btn_box['height'] / 2
                    _log(job_id, f"PW: #px-captcha box: {btn_box}")
                else:
                    cx = iframe_box['x'] + iframe_box['width'] / 2
                    cy = iframe_box['y'] + iframe_box['height'] / 2
                    _log(job_id, f"PW: Using iframe center as fallback. iframe_box={iframe_box}")

            # ============================================================
            # STRATEGY 1: ACCESSIBLE CHALLENGE (preferred — no detection)
            # Click accessibility icon → bar auto-fills → click again
            # ============================================================
            if attempt <= 4:  # Try accessible first
                acc_solved = _try_accessible_challenge(page, frame, iframe_handle, job_id)
                if acc_solved:
                    return True
                _log(job_id, "PW: Accessible challenge failed, trying press-and-hold...")

            # ============================================================
            # STRATEGY 2: CDP PRESS-AND-HOLD (fallback)
            # ============================================================
            if attempt <= 2:
                hold_dur = random.uniform(14, 18)
            else:
                hold_dur = random.uniform(18, 24)

            _log(job_id, f"PW: Press at ({cx:.0f}, {cy:.0f}) for {hold_dur:.1f}s [method=CDP]")

            start = time.time()
            solved = False
            
            # Use CDP for mouse events (less detectable)
            try:
                cdp = page.context.new_cdp_session(page)
                
                cdp.send("Input.dispatchMouseEvent", {
                    "type": "mouseMoved", "x": int(cx), "y": int(cy),
                })
                time.sleep(random.uniform(0.15, 0.35))
                
                cdp.send("Input.dispatchMouseEvent", {
                    "type": "mousePressed", "x": int(cx), "y": int(cy),
                    "button": "left", "clickCount": 1,
                })
                
                while time.time() - start < hold_dur:
                    time.sleep(random.uniform(0.3, 0.7))
                    dx = random.choice([-2, -1, 0, 1, 2])
                    dy = random.choice([-1, 0, 1])
                    try:
                        cdp.send("Input.dispatchMouseEvent", {
                            "type": "mouseMoved", "x": int(cx + dx), "y": int(cy + dy),
                        })
                    except:
                        pass
                    try:
                        if "abuse" not in page.url.lower():
                            solved = True
                            break
                    except:
                        pass

                cdp.send("Input.dispatchMouseEvent", {
                    "type": "mouseReleased", "x": int(cx), "y": int(cy),
                    "button": "left", "clickCount": 1,
                })
                cdp.detach()
            except Exception as cdp_err:
                _log(job_id, f"PW: CDP error: {str(cdp_err)[:150]}, fallback page.mouse", "warning")
                try:
                    page.mouse.move(cx, cy)
                    time.sleep(0.2)
                    page.mouse.down()
                    start = time.time()
                    while time.time() - start < hold_dur:
                        time.sleep(random.uniform(0.4, 0.8))
                        page.mouse.move(cx + random.choice([-2,-1,0,1,2]), cy + random.choice([-1,0,1]))
                        try:
                            if "abuse" not in page.url.lower():
                                solved = True
                                break
                        except:
                            pass
                    page.mouse.up()
                except:
                    pass
            
            elapsed = time.time() - start
            _log(job_id, f"PW: Released after {elapsed:.1f}s, solved={solved}")

            if solved:
                _log(job_id, "PW: ✓ Solved during hold!")
                return True

            # Wait and check
            for wait_i in range(8):
                time.sleep(5)
                try:
                    if "abuse" not in page.url.lower():
                        _log(job_id, f"PW: ✓ Solved after {(wait_i+1)*5}s!")
                        return True
                except:
                    pass
                try:
                    body = page.inner_text("body").lower()
                    if "press and hold" in body or "try again" in body or "pressione" in body:
                        _log(job_id, "PW: 'Try again' detected, will retry")
                        break
                except:
                    pass

        except Exception as e:
            _log(job_id, f"PW: Error in attempt {attempt}: {str(e)[:200]}", "warning")

        time.sleep(random.uniform(2, 4))

    _log(job_id, "PW: ✗ Playwright solver failed", "warning")
    return False


def check_captcha_solved(page) -> bool:
    """Check if CAPTCHA is solved (Playwright page)."""
    try:
        url = page.url.lower()
        if "abuse" not in url and "signup.live.com" not in url:
            return True
    except:
        pass
    return False
