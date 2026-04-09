"""
PerimeterX "Press and Hold" CAPTCHA Solver.
Uses undetected-chromedriver (Selenium) since Playwright's Chromium fails PX fingerprinting.
After solving, returns so the main Playwright flow can continue.
"""

import time
import random
import logging
import os

logger = logging.getLogger("CAPTCHA")

UC_CHROMEDRIVER = "/home/user/chromedriver"


def solve_captcha_with_uc(email: str, password: str, max_attempts: int = 3) -> bool:
    """
    Solve the CAPTCHA using undetected-chromedriver.
    Logs into the account, handles the Abuse page + CAPTCHA.
    After solving, the account should be unlocked for subsequent Playwright sessions.
    
    Returns True if account was unlocked, False if failed.
    """
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    os.environ.setdefault("DISPLAY", ":99")

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    logger.info(f"Starting UC Chrome for CAPTCHA solving...")
    driver = None
    
    try:
        # Auto-detect Chrome version
        chrome_version = None
        try:
            import subprocess
            out = subprocess.check_output(["google-chrome", "--version"], stderr=subprocess.DEVNULL).decode()
            chrome_version = int(out.strip().split()[-1].split(".")[0])
            logger.info(f"Detected Chrome version: {chrome_version}")
        except:
            chrome_version = None

        uc_kwargs = {"options": options}
        if chrome_version:
            uc_kwargs["version_main"] = chrome_version

        driver = uc.Chrome(**uc_kwargs)

        # Step 1: Login
        logger.info("UC: Logging in...")
        driver.get("https://login.live.com/")
        time.sleep(3)

        email_input = driver.find_element(By.CSS_SELECTOR, "input[type=email]")
        email_input.send_keys(email)
        time.sleep(0.5)

        try:
            driver.find_element(By.CSS_SELECTOR, "#idSIButton9").click()
        except:
            email_input.send_keys("\n")
        time.sleep(4)

        # Password
        logger.info("UC: Entering password...")
        pwd_input = driver.find_element(By.CSS_SELECTOR, "input[type=password]")
        pwd_input.send_keys(password)
        time.sleep(0.5)

        try:
            driver.find_element(By.CSS_SELECTOR, "#idSIButton9").click()
        except:
            pwd_input.send_keys("\n")
        time.sleep(5)

        url = driver.current_url.lower()
        logger.info(f"UC: Post-login URL: {driver.current_url}")

        # If not on abuse page, account is already unlocked
        if "abuse" not in url:
            logger.info("UC: No abuse page — account already unlocked!")
            return True

        # Step 2: Click "Next" on the intro page
        logger.info("UC: Clicking Next on intro page...")
        try:
            btns = driver.find_elements(By.TAG_NAME, "button")
            for btn in btns:
                if "next" in btn.text.lower() or "próximo" in btn.text.lower():
                    btn.click()
                    break
        except:
            pass
        time.sleep(5)

        # Step 3: Solve CAPTCHA
        for attempt in range(1, max_attempts + 1):
            logger.info(f"UC: CAPTCHA attempt {attempt}/{max_attempts}")

            # Check if already solved
            if "abuse" not in driver.current_url.lower():
                logger.info("UC: ✓ CAPTCHA already solved!")
                return True

            # Find the hsprotect iframe
            captcha_iframe = None
            for iframe in driver.find_elements(By.TAG_NAME, "iframe"):
                src = (iframe.get_attribute("src") or "").lower()
                if "hsprotect" in src or "enforcement" in src:
                    rect = iframe.rect
                    if rect['width'] > 50:
                        captcha_iframe = iframe
                        break

            if not captcha_iframe:
                logger.info("UC: No CAPTCHA iframe found, waiting...")
                time.sleep(5)
                continue

            # Scroll into view
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", captcha_iframe
            )
            time.sleep(0.5)

            iframe_rect = driver.execute_script(
                "var r=arguments[0].getBoundingClientRect();"
                "return{x:r.x,y:r.y,w:r.width,h:r.height};",
                captcha_iframe
            )

            # Get button position inside iframe
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

            # Calculate click offset
            if btn_rect and btn_rect['w'] > 10:
                off_x = int(btn_rect['x'] + btn_rect['w'] / 2 - iframe_rect['w'] / 2)
                off_y = int(btn_rect['y'] + btn_rect['h'] / 2 - iframe_rect['h'] / 2)
            else:
                off_x, off_y = 0, int(iframe_rect['h'] * 0.2)

            hold_duration = random.uniform(16, 22)
            logger.info(f"UC: Hold at offset ({off_x}, {off_y}) for {hold_duration:.1f}s")

            # Press and hold with micro-movements
            ac = ActionChains(driver)
            ac.move_to_element_with_offset(
                captcha_iframe, off_x, off_y
            ).pause(0.3).click_and_hold().perform()

            start = time.time()
            solved = False
            while time.time() - start < hold_duration:
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
                        solved = True
                        break
                except:
                    pass

            try:
                ActionChains(driver).release().perform()
            except:
                pass

            elapsed = time.time() - start
            logger.info(f"UC: Released after {elapsed:.1f}s")

            if solved:
                logger.info("UC: ✓ Solved during hold!")
                return True

            # Wait for the loading spinner to resolve
            logger.info("UC: Waiting for page to settle...")
            for wait_i in range(12):
                time.sleep(5)
                url = driver.current_url.lower()
                try:
                    body = driver.find_element(By.TAG_NAME, "body").text.lower()
                except:
                    body = ""

                if "abuse" not in url:
                    logger.info(f"UC: ✓ Solved after {(wait_i + 1) * 5}s wait!")
                    return True

                if "press and hold" in body or "try again" in body:
                    logger.info(f"UC: Need to retry (body: {body[:60]})")
                    break

                if "loading" in body:
                    continue  # Still loading, keep waiting

            time.sleep(random.uniform(2, 4))

        logger.error("UC: ✗ CAPTCHA failed after all attempts")
        return False

    except Exception as e:
        logger.error(f"UC: Error: {str(e)[:100]}")
        return False

    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass


# Legacy Playwright-based functions (kept for compatibility but may not solve CAPTCHA)

def check_captcha_solved(page) -> bool:
    """Check if CAPTCHA is solved."""
    try:
        url = page.url.lower()
        if "abuse" not in url and "signup.live.com" not in url:
            return True
    except:
        pass
    try:
        body = page.inner_text("body").lower()
        if "press and hold" not in body and "pressione e segure" not in body:
            return True
    except:
        pass
    return False


def solve_press_and_hold(page, max_attempts: int = 5) -> bool:
    """Legacy Playwright CAPTCHA solver — may not work due to fingerprinting."""
    logger.info("🔒 Attempting Playwright CAPTCHA solve (may fail)...")
    # ... simplified version just in case
    for attempt in range(1, max_attempts + 1):
        logger.info(f"  Attempt {attempt}/{max_attempts}")
        time.sleep(2)
        if check_captcha_solved(page):
            return True

        try:
            frame_loc = page.frame_locator("iframe[src*='hsprotect']").first
            px_el = frame_loc.locator("#px-captcha")
            box = px_el.bounding_box(timeout=5000)
            if box:
                cx = box['x'] + box['width'] / 2
                cy = box['y'] + box['height'] / 2
                page.mouse.move(cx, cy)
                time.sleep(0.2)
                page.mouse.down()
                start = time.time()
                dur = random.uniform(16, 22)
                while time.time() - start < dur:
                    time.sleep(random.uniform(0.3, 0.7))
                    page.mouse.move(
                        cx + random.choice([-1, 0, 1]),
                        cy + random.choice([-1, 0, 1])
                    )
                page.mouse.up()
                time.sleep(5)
                if check_captcha_solved(page):
                    return True
        except:
            pass
        time.sleep(3)

    return False
