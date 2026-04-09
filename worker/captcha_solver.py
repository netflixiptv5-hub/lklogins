"""
PerimeterX "Press and Hold" CAPTCHA Solver.
Uses undetected-chromedriver (Selenium) since Playwright's Chromium fails PX fingerprinting.
After solving, returns so the main Playwright flow can continue.

Also includes a Playwright-based solver as a faster first attempt.
"""

import time
import random
import logging
import os
import subprocess

logger = logging.getLogger("CAPTCHA")


def _ensure_display():
    """Ensure Xvfb is running."""
    display = os.environ.get("DISPLAY", "")
    if not display:
        os.environ["DISPLAY"] = ":99"
    # Check if Xvfb is running
    try:
        result = subprocess.run(["pgrep", "-f", "Xvfb"], capture_output=True, timeout=3)
        if result.returncode != 0:
            subprocess.Popen(
                ["Xvfb", ":99", "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            time.sleep(1)
            logger.info("Started Xvfb on :99")
    except:
        pass


def _get_chrome_version():
    """Detect installed Chrome major version."""
    try:
        out = subprocess.check_output(
            ["google-chrome", "--version"], stderr=subprocess.DEVNULL
        ).decode().strip()
        # "Google Chrome 146.0.7680.177" -> 146
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
    # Also check if captcha iframe is gone
    try:
        still_visible = driver.execute_script("""
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
        if not still_visible:
            # No captcha iframe visible — might be solved
            url = driver.current_url.lower()
            if "abuse" not in url:
                return True
    except:
        pass
    return False


def _do_press_and_hold(driver, captcha_iframe, attempt_num):
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

    # Vary hold duration: first attempts shorter, later longer
    if attempt_num <= 2:
        hold_duration = random.uniform(14, 18)
    else:
        hold_duration = random.uniform(18, 24)

    logger.info(f"UC: Hold at offset ({off_x}, {off_y}) for {hold_duration:.1f}s [attempt {attempt_num}]")

    # Press and hold with micro-movements (humanization)
    ac = ActionChains(driver)
    ac.move_to_element_with_offset(
        captcha_iframe, off_x, off_y
    ).pause(random.uniform(0.2, 0.5)).click_and_hold().perform()

    start = time.time()
    solved = False
    while time.time() - start < hold_duration:
        time.sleep(random.uniform(0.4, 0.9))
        # Micro-movements to simulate human hand tremor
        try:
            ActionChains(driver).move_by_offset(
                random.choice([-2, -1, 0, 1, 2]),
                random.choice([-1, 0, 1])
            ).perform()
        except:
            pass
        # Check if URL changed (solved during hold)
        try:
            if "abuse" not in driver.current_url.lower():
                solved = True
                break
        except:
            pass

    # Release
    try:
        ActionChains(driver).release().perform()
    except:
        pass

    elapsed = time.time() - start
    logger.info(f"UC: Released after {elapsed:.1f}s, solved_during_hold={solved}")
    return solved


def solve_captcha_with_uc(email: str, password: str, max_attempts: int = 5) -> bool:
    """
    Solve the PerimeterX CAPTCHA using undetected-chromedriver.
    Logs into the account, handles the Abuse page + CAPTCHA.
    
    Returns True if account was unlocked, False if failed.
    """
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    _ensure_display()

    chrome_version = _get_chrome_version()
    logger.info(f"Chrome version: {chrome_version}")

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=pt-BR")

    driver = None
    try:
        uc_kwargs = {"options": options}
        if chrome_version:
            uc_kwargs["version_main"] = chrome_version

        logger.info("Starting UC Chrome...")
        driver = uc.Chrome(**uc_kwargs)
        driver.set_page_load_timeout(30)

        # === Step 1: Login ===
        logger.info("UC: Navigating to login...")
        driver.get("https://login.live.com/")
        time.sleep(random.uniform(2, 4))

        # Email
        email_input = driver.find_element(By.CSS_SELECTOR, "input[type=email]")
        # Type slowly like a human
        for char in email:
            email_input.send_keys(char)
            time.sleep(random.uniform(0.03, 0.08))
        time.sleep(0.5)

        try:
            driver.find_element(By.CSS_SELECTOR, "#idSIButton9").click()
        except:
            email_input.send_keys("\n")
        time.sleep(random.uniform(3, 5))

        # Password
        logger.info("UC: Entering password...")
        pwd_input = driver.find_element(By.CSS_SELECTOR, "input[type=password]")
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
        logger.info(f"UC: Post-login URL: {driver.current_url}")

        # If not on abuse page, account is already unlocked
        if "abuse" not in url:
            logger.info("UC: No abuse page — account already unlocked!")
            return True

        # === Step 2: Handle the abuse intro page ===
        logger.info("UC: On abuse page, looking for Next button...")
        time.sleep(2)
        
        # Try clicking Next/Próximo
        clicked_next = False
        for _ in range(3):
            try:
                btns = driver.find_elements(By.TAG_NAME, "button")
                for btn in btns:
                    txt = btn.text.lower().strip()
                    if txt in ("next", "próximo", "siguiente", "avançar"):
                        btn.click()
                        clicked_next = True
                        break
                if clicked_next:
                    break
            except:
                pass
            # Also try input[type=submit]
            try:
                submits = driver.find_elements(By.CSS_SELECTOR, "input[type=submit]")
                for s in submits:
                    val = (s.get_attribute("value") or "").lower()
                    if val in ("next", "próximo", "siguiente", "avançar"):
                        s.click()
                        clicked_next = True
                        break
                if clicked_next:
                    break
            except:
                pass
            time.sleep(2)

        if clicked_next:
            logger.info("UC: Clicked Next, waiting for CAPTCHA...")
        time.sleep(random.uniform(4, 6))

        # === Step 3: Solve CAPTCHA ===
        for attempt in range(1, max_attempts + 1):
            logger.info(f"UC: CAPTCHA attempt {attempt}/{max_attempts}")

            if _check_abuse_solved(driver):
                logger.info("UC: ✓ CAPTCHA already solved!")
                return True

            # Find the captcha iframe
            captcha_iframe = None
            for iframe in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    src = (iframe.get_attribute("src") or "").lower()
                    if "hsprotect" in src or "enforcement" in src or "arkose" in src:
                        rect = iframe.rect
                        if rect.get('width', 0) > 50:
                            captcha_iframe = iframe
                            break
                except:
                    continue

            if not captcha_iframe:
                logger.info("UC: No CAPTCHA iframe found, waiting...")
                time.sleep(5)
                if _check_abuse_solved(driver):
                    logger.info("UC: ✓ Solved while waiting for iframe!")
                    return True
                continue

            # Execute press and hold
            solved_during_hold = _do_press_and_hold(driver, captcha_iframe, attempt)

            if solved_during_hold:
                logger.info("UC: ✓ Solved during hold!")
                return True

            # Wait for the page to settle after release
            logger.info("UC: Waiting for page to settle after release...")
            for wait_i in range(15):  # Up to 75 seconds
                time.sleep(5)
                
                url = driver.current_url.lower()
                if "abuse" not in url:
                    logger.info(f"UC: ✓ Solved after {(wait_i + 1) * 5}s wait!")
                    return True

                try:
                    body = driver.find_element(By.TAG_NAME, "body").text.lower()
                except:
                    body = ""

                # Check if there's a "try again" or "press and hold" message
                if any(t in body for t in ["press and hold", "try again", "pressione e segure", "tente novamente"]):
                    logger.info(f"UC: Need to retry (text found in body)")
                    break

                # If loading, keep waiting
                if "loading" in body or body.strip() == "":
                    continue

            time.sleep(random.uniform(2, 5))

        logger.error("UC: ✗ CAPTCHA failed after all attempts")
        return False

    except Exception as e:
        logger.error(f"UC: Error: {str(e)[:200]}")
        import traceback
        logger.error(f"UC: Traceback: {traceback.format_exc()[-300:]}")
        return False

    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass


# ==================== PLAYWRIGHT-BASED SOLVER ====================

def solve_captcha_playwright(page, max_attempts: int = 4) -> bool:
    """
    Try to solve PerimeterX CAPTCHA directly in Playwright.
    Faster than UC but may fail due to fingerprinting.
    Worth trying first before falling back to UC.
    """
    logger.info("PW: Attempting Playwright CAPTCHA solve...")

    for attempt in range(1, max_attempts + 1):
        logger.info(f"PW: Attempt {attempt}/{max_attempts}")

        # Check if already solved
        try:
            url = page.url.lower()
            if "abuse" not in url:
                logger.info("PW: ✓ Already solved!")
                return True
        except:
            pass

        # Find captcha iframe
        try:
            # Try multiple iframe selectors
            iframe_handle = None
            for selector in [
                "iframe[src*='hsprotect']",
                "iframe[src*='enforcement']",
                "iframe[src*='arkose']",
            ]:
                try:
                    loc = page.locator(selector).first
                    if loc.is_visible(timeout=3000):
                        iframe_handle = loc
                        break
                except:
                    continue

            if not iframe_handle:
                logger.info("PW: No captcha iframe found")
                time.sleep(3)
                continue

            # Get iframe bounding box
            iframe_box = iframe_handle.bounding_box()
            if not iframe_box or iframe_box['width'] < 50:
                logger.info("PW: Iframe too small or invisible")
                time.sleep(3)
                continue

            # Try to find #px-captcha inside the iframe
            frame = page.frame_locator("iframe[src*='hsprotect'], iframe[src*='enforcement'], iframe[src*='arkose']").first
            px_btn = frame.locator("#px-captcha")
            
            try:
                btn_box = px_btn.bounding_box(timeout=5000)
            except:
                btn_box = None

            if btn_box and btn_box['width'] > 10:
                cx = btn_box['x'] + btn_box['width'] / 2
                cy = btn_box['y'] + btn_box['height'] / 2
            else:
                # Fallback: center of iframe
                cx = iframe_box['x'] + iframe_box['width'] / 2
                cy = iframe_box['y'] + iframe_box['height'] / 2

            # Hold duration
            if attempt <= 2:
                hold_dur = random.uniform(14, 18)
            else:
                hold_dur = random.uniform(18, 24)

            logger.info(f"PW: Press at ({cx:.0f}, {cy:.0f}) for {hold_dur:.1f}s")

            # Move to position
            page.mouse.move(cx, cy)
            time.sleep(random.uniform(0.2, 0.4))
            
            # Press and hold
            page.mouse.down()
            start = time.time()
            solved = False

            while time.time() - start < hold_dur:
                time.sleep(random.uniform(0.4, 0.8))
                # Micro-movements
                page.mouse.move(
                    cx + random.choice([-2, -1, 0, 1, 2]),
                    cy + random.choice([-1, 0, 1])
                )
                # Check if solved
                try:
                    if "abuse" not in page.url.lower():
                        solved = True
                        break
                except:
                    pass

            page.mouse.up()
            elapsed = time.time() - start
            logger.info(f"PW: Released after {elapsed:.1f}s")

            if solved:
                logger.info("PW: ✓ Solved during hold!")
                return True

            # Wait and check
            for wait_i in range(10):
                time.sleep(5)
                try:
                    if "abuse" not in page.url.lower():
                        logger.info(f"PW: ✓ Solved after {(wait_i+1)*5}s!")
                        return True
                except:
                    pass
                try:
                    body = page.inner_text("body").lower()
                    if "press and hold" in body or "try again" in body or "pressione" in body:
                        break
                except:
                    pass

        except Exception as e:
            logger.warning(f"PW: Error in attempt {attempt}: {str(e)[:100]}")

        time.sleep(random.uniform(2, 4))

    logger.warning("PW: ✗ Playwright solver failed")
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
