"""
🌑 DARKSAGE - Outlook Mass Creator v22
MODO 1: VPN (sem proxy, usa IP da VPN)
MODO 2: Proxy (proxy local por bot, IPs BR únicos)
3 CMDs separados | Só conta sucesso | Banco JSON anti-repetição
"""

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import requests
import time
import random
import os
import sys
import tempfile
import uuid
import shutil
import subprocess
import json
import threading
import socket
import select
import base64


# ===================== CONFIG =====================

SENHA_FIXA = "02022013L"
ARQUIVO_SAIDA = "contas_criadas.txt"
ARQUIVO_DB = "contas_db.json"

PROXY_HOST = "rp.scrapegw.com"
PROXY_PORT = 6060
PROXY_USER = "yge2rofgqga7m82"
PROXY_PASS = "oghr0klsnmgqfan"

SIGNUP_URL = "https://signup.live.com/signup?mkt=PT-BR&uiflavor=web&lw=1&fl=dob%2cflname%2cwld&lic=1"

# Modo global: "vpn" ou "proxy"
MODO = "vpn"

# ===================== DADOS BR =====================

PRIMEIROS_NOMES_M = [
    "Lucas", "Pedro", "Gabriel", "Rafael", "Matheus", "Gustavo", "Bruno",
    "Felipe", "Leonardo", "Thiago", "Carlos", "Daniel", "Marcos", "Andre",
    "Rodrigo", "Fernando", "Henrique", "Diego", "Vitor", "Ricardo",
    "Eduardo", "Alexandre", "Joao", "Paulo", "Marcelo", "Fabio", "Leandro",
    "Roberto", "Samuel", "Caio", "Murilo", "Renan", "Igor", "Arthur",
    "Enzo", "Nicolas", "Bernardo", "Heitor", "Davi", "Miguel"
]
PRIMEIROS_NOMES_F = [
    "Ana", "Maria", "Julia", "Beatriz", "Larissa", "Fernanda", "Camila",
    "Amanda", "Leticia", "Bruna", "Mariana", "Carolina", "Isabela", "Rafaela",
    "Gabriela", "Tatiana", "Patricia", "Vanessa", "Juliana", "Renata",
    "Aline", "Priscila", "Natalia", "Daniela", "Bianca", "Vitoria", "Laura",
    "Sophia", "Helena", "Valentina", "Alice", "Manuela", "Cecilia", "Luana",
    "Giovanna", "Isadora", "Lorena", "Raquel", "Monica", "Sabrina"
]
SOBRENOMES = [
    "Silva", "Santos", "Oliveira", "Souza", "Pereira", "Costa", "Rodrigues",
    "Almeida", "Nascimento", "Lima", "Araujo", "Fernandes", "Carvalho",
    "Gomes", "Martins", "Rocha", "Ribeiro", "Alves", "Monteiro", "Mendes",
    "Barros", "Freitas", "Barbosa", "Pinto", "Moreira", "Campos", "Cardoso",
    "Teixeira", "Vieira", "Nunes", "Lopes", "Correia", "Batista", "Dias",
    "Ramos", "Moura", "Ferreira", "Melo", "Cunha", "Azevedo"
]
MESES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
}


# ===================== BANCO JSON =====================

def _carregar_db():
    if not os.path.exists(ARQUIVO_DB):
        return {"contas": [], "emails_usados": []}
    try:
        with open(ARQUIVO_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"contas": [], "emails_usados": []}

def _salvar_conta_db(email, senha, ip, bot_id, sucesso=True):
    from datetime import datetime
    lock_path = ARQUIVO_DB + ".lock"
    for _ in range(50):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            time.sleep(0.1)
    try:
        db = _carregar_db()
        registro = {
            "email": email, "senha": senha, "ip": ip,
            "bot": bot_id, "sucesso": sucesso,
            "data": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        db["contas"].append(registro)
        if email not in db["emails_usados"]:
            db["emails_usados"].append(email)
        with open(ARQUIVO_DB, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
    finally:
        try:
            os.remove(lock_path)
        except:
            pass

def _email_ja_usado(email):
    db = _carregar_db()
    return email.lower() in [e.lower() for e in db["emails_usados"]]

def _registrar_email_tentativa(email):
    lock_path = ARQUIVO_DB + ".lock"
    for _ in range(50):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            time.sleep(0.1)
    try:
        db = _carregar_db()
        if email.lower() not in [e.lower() for e in db["emails_usados"]]:
            db["emails_usados"].append(email)
            with open(ARQUIVO_DB, "w", encoding="utf-8") as f:
                json.dump(db, f, indent=2, ensure_ascii=False)
    finally:
        try:
            os.remove(lock_path)
        except:
            pass


# ===================== PROXY LOCAL =====================

class LocalProxyHandler:
    def __init__(self, local_port, session_id):
        self.local_port = local_port
        self.session_id = session_id
        self.proxy_user = f"{PROXY_USER}-country-br-session-{session_id}-lifetime-5"
        self.running = False
        self.server_socket = None
        self.thread = None

    def _get_proxy_auth(self):
        creds = f"{self.proxy_user}:{PROXY_PASS}"
        return base64.b64encode(creds.encode()).decode()

    def _handle_connect(self, client_socket, host, port):
        try:
            proxy_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            proxy_sock.settimeout(15)
            proxy_sock.connect((PROXY_HOST, PROXY_PORT))
            auth = self._get_proxy_auth()
            connect_req = (
                f"CONNECT {host}:{port} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                f"Proxy-Authorization: Basic {auth}\r\n"
                f"Proxy-Connection: close\r\n\r\n"
            )
            proxy_sock.sendall(connect_req.encode())
            response = b""
            while b"\r\n\r\n" not in response:
                chunk = proxy_sock.recv(4096)
                if not chunk:
                    break
                response += chunk
            status_line = response.split(b"\r\n")[0].decode(errors="ignore")
            if "200" in status_line:
                client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self._relay(client_socket, proxy_sock)
            else:
                client_socket.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            proxy_sock.close()
        except:
            try:
                client_socket.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            except:
                pass

    def _handle_http(self, client_socket, request_data):
        try:
            proxy_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            proxy_sock.settimeout(15)
            proxy_sock.connect((PROXY_HOST, PROXY_PORT))
            auth = self._get_proxy_auth()
            if b"\r\n\r\n" in request_data:
                header_end = request_data.index(b"\r\n\r\n")
                headers = request_data[:header_end]
                body = request_data[header_end:]
                auth_header = f"Proxy-Authorization: Basic {auth}\r\n".encode()
                first_line_end = headers.index(b"\r\n") + 2
                modified = headers[:first_line_end] + auth_header + headers[first_line_end:] + body
                proxy_sock.sendall(modified)
            else:
                proxy_sock.sendall(request_data)
            self._relay(client_socket, proxy_sock)
            proxy_sock.close()
        except:
            try:
                client_socket.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            except:
                pass

    def _relay(self, sock1, sock2):
        sockets = [sock1, sock2]
        timeout_count = 0
        while True:
            try:
                readable, _, errored = select.select(sockets, [], sockets, 1.0)
            except:
                break
            if errored:
                break
            if not readable:
                timeout_count += 1
                if timeout_count > 120:
                    break
                continue
            timeout_count = 0
            done = False
            for s in readable:
                try:
                    data = s.recv(65536)
                    if not data:
                        done = True
                        break
                    other = sock2 if s is sock1 else sock1
                    other.sendall(data)
                except:
                    done = True
                    break
            if done:
                break

    def _handle_client(self, client_socket):
        try:
            client_socket.settimeout(30)
            request_data = client_socket.recv(65536)
            if not request_data:
                client_socket.close()
                return
            first_line = request_data.split(b"\r\n")[0].decode(errors="ignore")
            parts = first_line.split()
            if len(parts) < 3:
                client_socket.close()
                return
            method = parts[0].upper()
            target = parts[1]
            if method == "CONNECT":
                if ":" in target:
                    host, port = target.rsplit(":", 1)
                    port = int(port)
                else:
                    host = target
                    port = 443
                self._handle_connect(client_socket, host, port)
            else:
                self._handle_http(client_socket, request_data)
        except:
            pass
        finally:
            try:
                client_socket.close()
            except:
                pass

    def start(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(("127.0.0.1", self.local_port))
        self.server_socket.listen(50)
        self.server_socket.settimeout(1.0)
        self.running = True

        def serve():
            while self.running:
                try:
                    client, addr = self.server_socket.accept()
                    t = threading.Thread(target=self._handle_client, args=(client,), daemon=True)
                    t.start()
                except socket.timeout:
                    continue
                except:
                    if self.running:
                        continue
                    break

        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        try:
            self.server_socket.close()
        except:
            pass

    def update_session(self, new_session_id):
        self.session_id = new_session_id
        self.proxy_user = f"{PROXY_USER}-country-br-session-{new_session_id}-lifetime-5"


def achar_porta_livre():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ===================== PRÉ-GERAR IPs =====================

def gerar_lista_ips(quantidade):
    print(f"\n  \033[93m🔍 Gerando {quantidade} IPs BR únicos...\033[0m\n")
    sessions = []
    ips_vistos = set()
    tentativas = 0
    max_tentativas = quantidade * 5

    while len(sessions) < quantidade and tentativas < max_tentativas:
        tentativas += 1
        session_id = f"pre_{uuid.uuid4().hex[:16]}"
        proxy_user = f"{PROXY_USER}-country-br-session-{session_id}-lifetime-5"
        try:
            proxies = {"https": f"http://{proxy_user}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"}
            resp = requests.get("https://api.ipify.org", proxies=proxies, timeout=12)
            ip = resp.text.strip()
            if ip and ip not in ips_vistos:
                ips_vistos.add(ip)
                sessions.append({"session": session_id, "ip": ip})
                print(f"  \033[92m  [{len(sessions):2d}/{quantidade}] {ip} ✓\033[0m")
            elif ip in ips_vistos:
                print(f"  \033[90m  [---] {ip} (repetido)\033[0m")
        except:
            print(f"  \033[90m  [---] timeout\033[0m")
        time.sleep(0.5)

    print(f"\n  \033[92m✅ {len(sessions)} IPs prontos!\033[0m\n")
    return sessions


# ===================== UTILS =====================

BOT_ID = 0
BOT_COR = "\033[96m"
BOT_CORES = ["\033[96m", "\033[93m", "\033[95m"]


def log(msg):
    reset = "\033[0m"
    print(f"{BOT_COR}[BOT {BOT_ID}]{reset} {msg}", flush=True)


def gerar_dados():
    for _ in range(100):
        sexo = random.choice(["M", "F"])
        primeiro_nome = random.choice(PRIMEIROS_NOMES_M if sexo == "M" else PRIMEIROS_NOMES_F)
        sobrenome = random.choice(SOBRENOMES)
        num = random.randint(100, 99999)
        username = f"{primeiro_nome.lower()}{sobrenome.lower()}{num}"
        email = f"{username}@outlook.com"
        if not _email_ja_usado(email):
            _registrar_email_tentativa(email)
            ano = random.randint(1981, 2007)
            mes = random.randint(1, 12)
            dia = random.randint(1, 28)
            return {
                "primeiro_nome": primeiro_nome,
                "sobrenome": sobrenome,
                "username": username,
                "email": email,
                "senha": SENHA_FIXA,
                "dia": dia, "mes": mes, "ano": ano,
            }
    username = f"user{uuid.uuid4().hex[:10]}"
    return {
        "primeiro_nome": "User", "sobrenome": "Auto",
        "username": username, "email": f"{username}@outlook.com",
        "senha": SENHA_FIXA, "dia": 15, "mes": 6, "ano": 1995,
    }


def create_driver(local_proxy_port=None):
    """Chrome UC — com ou sem proxy"""
    posicoes = [(0, 0), (640, 0), (1280, 0)]
    pos_x, pos_y = posicoes[(BOT_ID - 1) % 3]

    options = uc.ChromeOptions()
    options.add_argument(f"--window-size=640,900")
    options.add_argument(f"--window-position={pos_x},{pos_y}")

    if local_proxy_port:
        options.add_argument(f"--proxy-server=http://127.0.0.1:{local_proxy_port}")

    options.add_argument("--disable-popup-blocking")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--log-level=3")
    options.add_argument("--lang=pt-BR")
    options.add_argument("--disable-http2")

    if local_proxy_port:
        options.add_argument("--proxy-bypass-list=<-loopback>")

    prefs = {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        "profile.password_manager_leak_detection": False,
        "autofill.profile_enabled": False,
        "profile.default_content_setting_values.notifications": 2,
    }
    options.add_experimental_option("prefs", prefs)

    user_data = os.path.join(tempfile.gettempdir(), f"uc_{uuid.uuid4().hex[:12]}")
    os.makedirs(user_data, exist_ok=True)
    options.add_argument(f"--user-data-dir={user_data}")

    driver = uc.Chrome(
        options=options,
        use_subprocess=True,
        version_main=146,
    )

    try:
        driver.set_window_size(640, 900)
        driver.set_window_position(pos_x, pos_y)
    except:
        pass

    # Chrome sempre no topo (Windows)
    if os.name == 'nt':
        try:
            import ctypes
            user32 = ctypes.windll.user32
            time.sleep(1)

            def set_topmost(hwnd, _):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        title = buf.value.lower()
                        if "chrome" in title or "google" in title:
                            HWND_TOPMOST = -1
                            SWP_NOMOVE = 0x0002
                            SWP_NOSIZE = 0x0001
                            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(WNDENUMPROC(set_topmost), 0)
            log("✓ Chrome fixado no topo")
        except Exception as e:
            log(f"? Topmost falhou: {e}")

    try:
        driver.execute_cdp_cmd("WebAuthn.enable", {"enableUI": False})
        driver.execute_cdp_cmd("WebAuthn.addVirtualAuthenticator", {
            "options": {
                "protocol": "ctap2",
                "transport": "internal",
                "hasResidentKey": True,
                "hasUserVerification": True,
                "isUserVerified": True,
            }
        })
    except:
        pass

    return driver, user_data


def digitar_lento(element, texto, delay_min=0.05, delay_max=0.15):
    for char in texto:
        element.send_keys(char)
        time.sleep(random.uniform(delay_min, delay_max))


def esperar_pagina(driver, timeout=15):
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except:
        pass
    time.sleep(random.uniform(1.5, 2.5))


def encontrar_input(driver, name_contains=None, type_attr=None, timeout=20):
    for _ in range(timeout * 2):
        inputs = driver.find_elements(By.TAG_NAME, "input")
        for inp in inputs:
            if not inp.is_displayed():
                continue
            inp_name = (inp.get_attribute("name") or "").lower()
            inp_type = (inp.get_attribute("type") or "").lower()
            inp_ph = (inp.get_attribute("placeholder") or "").lower()
            inp_aria = (inp.get_attribute("aria-label") or "").lower()
            all_text = f"{inp_name} {inp_ph} {inp_aria}"
            if name_contains and name_contains.lower() in all_text:
                return inp
            if type_attr and not name_contains and inp_type == type_attr.lower():
                return inp
        time.sleep(0.5)
    raise Exception(f"Input não encontrado: name={name_contains}, type={type_attr}")


def clicar_botao_avancar(driver, timeout=15):
    for _ in range(timeout * 2):
        for btn in driver.find_elements(By.TAG_NAME, "button"):
            if not btn.is_displayed():
                continue
            text = (btn.text or "").strip().lower()
            if text in ["avançar", "avancar", "next", "seguinte"]:
                time.sleep(random.uniform(0.3, 0.7))
                btn.click()
                return True
        time.sleep(0.5)
    raise Exception("Botão Avançar não encontrado!")


def selecionar_dropdown_ms(driver, dropdown_id, valor_texto, timeout=10):
    valor_lower = valor_texto.lower().strip()
    dropdown = None
    for _ in range(timeout * 2):
        try:
            dropdown = driver.find_element(By.ID, dropdown_id)
            if dropdown.is_displayed():
                break
        except:
            pass
        time.sleep(0.5)
    if not dropdown:
        return False

    ActionChains(driver).move_to_element(dropdown).pause(0.3).click().perform()
    time.sleep(1)

    try:
        for opt in driver.find_elements(By.CSS_SELECTOR, "[role='option']"):
            if opt.is_displayed() and valor_lower in opt.text.lower():
                ActionChains(driver).move_to_element(opt).pause(0.2).click().perform()
                time.sleep(0.3)
                return True
    except:
        pass

    try:
        xpath = f"//*[contains(translate(text(),'ABCDEFGHIJKLMNOPQRSTUVWXYZÀÁÂÃÉÊÍÓÔÕÚÇ','abcdefghijklmnopqrstuvwxyzàáâãéêíóôõúç'),'{valor_lower}')]"
        for el in driver.find_elements(By.XPATH, xpath):
            if el.is_displayed() and el != dropdown and el.tag_name.lower() in ["button","div","li","span","option","p"]:
                ActionChains(driver).move_to_element(el).pause(0.2).click().perform()
                time.sleep(0.3)
                return True
    except:
        pass

    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    except:
        pass
    return False


def checar_captcha_resolvido(driver):
    try:
        if "signup.live.com" not in driver.current_url.lower():
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
            return True
    except:
        pass
    return False


def resolver_pressione_segure(driver, max_tentativas=5):
    log("🔒 CAPTCHA...")

    for t in range(1, max_tentativas + 1):
        log(f"  Tentativa {t}/{max_tentativas}")
        try:
            driver.switch_to.default_content()
            time.sleep(1)
            if checar_captcha_resolvido(driver):
                log("  ✓ Já resolvido!")
                return True

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
                time.sleep(3)
                if checar_captcha_resolvido(driver):
                    return True
                continue

            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", captcha_iframe)
            time.sleep(0.5)
            iframe_rect = driver.execute_script("var r=arguments[0].getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height};", captcha_iframe)

            driver.switch_to.frame(captcha_iframe)
            time.sleep(1)
            btn_rect = None
            try:
                px = driver.find_element(By.ID, "px-captcha")
                btn_rect = driver.execute_script("var r=arguments[0].getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height};", px)
            except:
                pass
            driver.switch_to.default_content()
            time.sleep(0.3)

            if btn_rect and btn_rect['w'] > 10:
                off_x = int(btn_rect['x'] + btn_rect['w']/2 - iframe_rect['w']/2)
                off_y = int(btn_rect['y'] + btn_rect['h']/2 - iframe_rect['h']/2)
            else:
                off_x, off_y = 0, int(iframe_rect['h'] * 0.2)

            dur = random.uniform(14, 20)
            log(f"  Hold {dur:.0f}s...")

            ac = ActionChains(driver)
            ac.move_to_element_with_offset(captcha_iframe, off_x, off_y).pause(0.3).click_and_hold().perform()

            inicio = time.time()
            resolvido = False
            while time.time() - inicio < dur:
                time.sleep(random.uniform(0.5, 1.0))
                try:
                    ActionChains(driver).move_by_offset(random.choice([-1,0,1]), random.choice([-1,0,1])).perform()
                except:
                    pass
                try:
                    if "signup.live.com" not in driver.current_url.lower():
                        resolvido = True
                        break
                except:
                    pass

            try:
                ActionChains(driver).release().perform()
            except:
                pass
            log(f"  Solto {time.time()-inicio:.1f}s")

            if resolvido:
                log("  ✓ Resolvido durante hold!")
                return True
            time.sleep(4)
            if checar_captcha_resolvido(driver):
                log("  ✓ Resolvido!")
                return True
            time.sleep(random.uniform(2, 4))

        except Exception as e:
            log(f"  ! {str(e)[:50]}")
            try:
                driver.switch_to.default_content()
            except:
                pass
            if checar_captcha_resolvido(driver):
                return True
            time.sleep(2)

    log("✗ CAPTCHA falhou 5x — pulando conta")
    return False


# ===================== CRIAR CONTA =====================

def criar_uma_conta(session_info, local_proxy):
    """Cria conta — funciona com proxy ou VPN"""
    ip_esperado = session_info.get("ip", "VPN")

    # Se proxy, atualiza session
    if local_proxy and "session" in session_info:
        local_proxy.update_session(session_info["session"])
        time.sleep(0.5)

    dados = gerar_dados()

    log(f"📧 {dados['email']}")
    log(f"👤 {dados['primeiro_nome']} {dados['sobrenome']}  📅 {dados['dia']:02d}/{dados['mes']:02d}/{dados['ano']}")
    log(f"🌍 IP: {ip_esperado}")

    driver = None
    user_data = None
    try:
        proxy_port = local_proxy.local_port if local_proxy else None
        driver, user_data = create_driver(proxy_port)
        log("✓ Chrome iniciado")

        # CHECAR IP
        log("Verificando IP...")
        try:
            driver.get("https://api.ipify.org?format=json")
            time.sleep(3)
            meu_ip = driver.find_element(By.TAG_NAME, "body").text.strip()
            log(f"✓ IP: {meu_ip}")
        except Exception as e:
            log(f"? IP check falhou: {e}")
        time.sleep(1)

        # PASSO 1: Email
        log("─── Passo 1: Email ───")
        driver.get(SIGNUP_URL)
        time.sleep(4)
        esperar_pagina(driver)

        email_input = encontrar_input(driver, name_contains="email", type_attr="email")
        time.sleep(random.uniform(0.8, 2))
        email_input.click()
        time.sleep(0.5)
        digitar_lento(email_input, dados["email"])
        time.sleep(random.uniform(0.5, 1))

        try:
            clicar_botao_avancar(driver)
        except:
            try:
                driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
            except:
                email_input.send_keys(Keys.ENTER)

        log("✓ Email")
        time.sleep(random.uniform(3, 5))
        esperar_pagina(driver)

        # Checar duplicado
        for _ in range(3):
            try:
                bt = driver.find_element(By.TAG_NAME, "body").text.lower()
                if "já é uma conta" in bt or "already" in bt:
                    dados["username"] = f"{dados['primeiro_nome'].lower()}{dados['sobrenome'].lower()}{random.randint(10000, 99999)}"
                    dados["email"] = f"{dados['username']}@outlook.com"
                    log(f"Duplicado → {dados['email']}")
                    ei = encontrar_input(driver, name_contains="email", type_attr="email")
                    ei.click()
                    ei.send_keys(Keys.CONTROL + "a")
                    time.sleep(0.1)
                    ei.send_keys(Keys.DELETE)
                    time.sleep(0.2)
                    digitar_lento(ei, dados["email"])
                    time.sleep(0.5)
                    try:
                        clicar_botao_avancar(driver)
                    except:
                        ei.send_keys(Keys.ENTER)
                    time.sleep(3)
                    esperar_pagina(driver)
                else:
                    break
            except:
                break

        # PASSO 2: Senha
        log("─── Passo 2: Senha ───")
        senha_input = encontrar_input(driver, type_attr="password")
        time.sleep(random.uniform(0.8, 2))
        senha_input.click()
        time.sleep(0.5)
        digitar_lento(senha_input, dados["senha"])
        time.sleep(random.uniform(0.5, 1.5))
        clicar_botao_avancar(driver)
        log("✓ Senha")
        time.sleep(random.uniform(2, 4))
        esperar_pagina(driver)

        # PASSO 3: Nascimento
        log("─── Passo 3: Nascimento ───")
        time.sleep(1)
        selecionar_dropdown_ms(driver, "BirthDayDropdown", str(dados["dia"]))
        time.sleep(random.uniform(0.5, 1))
        selecionar_dropdown_ms(driver, "BirthMonthDropdown", MESES_PT[dados["mes"]])
        time.sleep(random.uniform(0.5, 1))
        try:
            ano_input = encontrar_input(driver, name_contains="BirthYear")
        except:
            ano_input = encontrar_input(driver, type_attr="number")
        ano_input.click()
        time.sleep(0.2)
        ano_input.send_keys(Keys.CONTROL + "a")
        time.sleep(0.1)
        ano_input.send_keys(Keys.DELETE)
        time.sleep(0.2)
        digitar_lento(ano_input, str(dados["ano"]))
        time.sleep(random.uniform(0.5, 1))
        clicar_botao_avancar(driver)
        log("✓ Nascimento")
        time.sleep(random.uniform(2, 4))
        esperar_pagina(driver)

        # PASSO 4: Nome
        log(f"─── Passo 4: Nome ───")
        time.sleep(1)
        primeiro_input = None
        ultimo_input = None
        for nid in ["firstNameInput", "FirstName", "iFirstName"]:
            try:
                el = driver.find_element(By.ID, nid)
                if el.is_displayed():
                    primeiro_input = el
                    break
            except:
                pass
        for sid in ["lastNameInput", "LastName", "iLastName"]:
            try:
                el = driver.find_element(By.ID, sid)
                if el.is_displayed():
                    ultimo_input = el
                    break
            except:
                pass

        if not primeiro_input or not ultimo_input:
            text_inputs = [i for i in driver.find_elements(By.TAG_NAME, "input")
                          if i.is_displayed() and (i.get_attribute("type") or "").lower() in ["text", ""]]
            if len(text_inputs) >= 2:
                primeiro_input = primeiro_input or text_inputs[0]
                ultimo_input = ultimo_input or text_inputs[1]

        if primeiro_input:
            primeiro_input.click()
            time.sleep(0.3)
            digitar_lento(primeiro_input, dados["primeiro_nome"])
        time.sleep(0.5)
        if ultimo_input:
            ultimo_input.click()
            time.sleep(0.3)
            digitar_lento(ultimo_input, dados["sobrenome"])
        time.sleep(0.5)
        clicar_botao_avancar(driver)
        log("✓ Nome")
        time.sleep(random.uniform(3, 5))
        esperar_pagina(driver)

        # CHECAR BLOCK
        time.sleep(2)
        pt = driver.find_element(By.TAG_NAME, "body").text.lower()
        if any(x in pt for x in ["não é possível", "something went wrong", "was blocked", "foi bloqueada", "try again"]):
            log("✗ BLOQUEADO")
            return False, None, None

        # PASSO 5: CAPTCHA
        log("─── Passo 5: CAPTCHA ───")
        time.sleep(3)
        if not resolver_pressione_segure(driver):
            return False, None, None

        # PÓS-CAPTCHA → ESPERAR MS PROCESSAR
        try:
            driver.switch_to.default_content()
        except:
            pass

        log("⏳ Esperando Microsoft processar a conta...")

        def url_eh_inbox(url):
            u = url.lower()
            return ("outlook.live.com/mail" in u or
                    "outlook.office.com/mail" in u or
                    "outlook.office365.com/mail" in u)

        # FASE 1: Esperar sair do signup (até 30s)
        # NÃO navega pra lugar nenhum, deixa a MS redirecionar sozinha
        conta_criada = False
        saiu_signup = False
        for i in range(30):
            time.sleep(2)
            try:
                url = driver.current_url.lower()
                if i % 3 == 0:
                    log(f"  URL: {url[:70]}")

                # Já tá no inbox? Show
                if url_eh_inbox(url):
                    conta_criada = True
                    break

                # Privacynotice = CONTA CRIADA! Vai direto pro inbox
                if "privacynotice" in url:
                    log("  ✓ Tela de privacidade = conta criada!")
                    time.sleep(2)
                    driver.get("https://outlook.live.com/mail/0/inbox")
                    time.sleep(5)
                    conta_criada = True
                    break

                # Saiu do signup? Boa, a conta foi criada
                if "signup.live.com" not in url:
                    saiu_signup = True

                    # Telas pós-criação (passkey, etc)
                    # Tenta clicar em qualquer botão de "pular/skip/continuar"
                    try:
                        for btn in driver.find_elements(By.TAG_NAME, "button"):
                            if not btn.is_displayed():
                                continue
                            txt = (btn.text or "").strip().lower()
                            if txt in ["skip", "pular", "skip for now", "não", "no", "continuar", "continue"]:
                                btn.click()
                                log(f"  → Clicou '{txt}'")
                                time.sleep(2)
                                break
                    except:
                        pass

                    # Se tá no login, vai pro inbox
                    if "login.live.com" in url or "account.live.com" in url:
                        time.sleep(2)
                        driver.get("https://outlook.live.com/mail/0/inbox")
                        time.sleep(5)
                        conta_criada = True
                        break

            except:
                pass

        # FASE 2: Se saiu do signup mas não chegou no inbox, agora sim força
        if not conta_criada and saiu_signup:
            log("🚀 Conta processada, indo pro inbox...")
            time.sleep(3)
            driver.get("https://outlook.live.com/mail/0/inbox")

            for i in range(20):
                time.sleep(3)
                try:
                    url = driver.current_url.lower()
                    if i % 4 == 0:
                        log(f"  URL: {url[:70]}")
                    if url_eh_inbox(url):
                        conta_criada = True
                        break
                    if "microsoft.com" in url and "outlook" not in url:
                        # Site marketing = conta pode não ter sido criada
                        log("  ⚠ Site marketing MS")
                        driver.get("https://outlook.live.com/mail/0/inbox")
                        time.sleep(5)
                    elif "login.live.com" in url:
                        time.sleep(3)
                        driver.get("https://outlook.live.com/mail/0/inbox")
                except:
                    pass

        # FASE 3: Última tentativa
        if not conta_criada:
            try:
                url = driver.current_url.lower()
                if url_eh_inbox(url):
                    conta_criada = True
                else:
                    driver.get("https://outlook.live.com/mail/0/inbox")
                    time.sleep(10)
                    if url_eh_inbox(driver.current_url.lower()):
                        conta_criada = True
            except:
                pass

        if conta_criada:
            # VERIFICAÇÃO FINAL: só conta se o inbox carregou DE VERDADE
            log("🔍 Verificando inbox real...")
            inbox_confirmado = False
            for check in range(30):
                time.sleep(2)
                try:
                    body = driver.find_element(By.TAG_NAME, "body").text.lower()
                    # Textos que SÓ aparecem no inbox real do Outlook
                    if any(t in body for t in [
                        "caixa de entrada", "inbox",
                        "bem-vindo", "welcome",
                        "novo email", "new email", "new message",
                        "página inicial", "home",
                        "itens enviados", "sent items",
                        "rascunhos", "drafts",
                        "equipe do outlook", "outlook team",
                        "selecionar um item", "select an item",
                        "nada foi selecionado", "nothing is selected"
                    ]):
                        inbox_confirmado = True
                        break
                except:
                    pass

                # A cada 10 checks, tenta dar refresh
                if check > 0 and check % 10 == 0:
                    try:
                        log("  ↻ Refresh inbox...")
                        driver.get("https://outlook.live.com/mail/0/inbox")
                        time.sleep(5)
                    except:
                        pass

                # Se URL saiu do outlook, desiste
                try:
                    url = driver.current_url.lower()
                    if "outlook" not in url and "live.com" not in url:
                        break
                except:
                    pass

            if inbox_confirmado:
                log(f"🎉 CONTA CRIADA: {dados['email']}")
                return True, dados["email"], dados["senha"]
            else:
                log("✗ Inbox não confirmado (página não carregou)")
                return False, None, None
        else:
            log("✗ NÃO criou (não chegou no inbox)")
            return False, None, None

    except Exception as e:
        log(f"✗ Erro: {e}")
        return False, None, None

    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
        if user_data:
            try:
                shutil.rmtree(user_data, ignore_errors=True)
            except:
                pass


# ===================== MODO BOT =====================

def rodar_bot(bot_id, sessions_json):
    global BOT_ID, BOT_COR
    BOT_ID = bot_id
    BOT_COR = BOT_CORES[(bot_id - 1) % 3]

    payload = json.loads(sessions_json)
    if isinstance(payload, dict):
        sessions = payload["sessions"]
        qtd = payload["meta"]
        modo = payload.get("modo", "vpn")
    else:
        sessions = payload
        qtd = len(sessions)
        modo = "vpn"

    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"{BOT_COR}")
    print(f"  ╔══════════════════════════════════════╗")
    print(f"  ║   DARKSAGE — BOT {bot_id}                  ║")
    print(f"  ║   META: {qtd} conta(s) | Modo: {modo.upper():5s}    ║")
    print(f"  ╚══════════════════════════════════════╝")
    print(f"\033[0m")

    # Iniciar proxy local se modo proxy
    local_proxy = None
    if modo == "proxy" and sessions:
        local_port = achar_porta_livre()
        local_proxy = LocalProxyHandler(local_port, sessions[0]["session"])
        local_proxy.start()
        log(f"✓ Proxy local em 127.0.0.1:{local_port}")

        log("Testando proxy local...")
        try:
            test_proxies = {"http": f"http://127.0.0.1:{local_port}", "https": f"http://127.0.0.1:{local_port}"}
            resp = requests.get("https://api.ipify.org", proxies=test_proxies, timeout=15)
            log(f"✓ Proxy OK → IP: {resp.text.strip()}")
        except Exception as e:
            log(f"⚠ Teste proxy falhou: {e}")
    else:
        log("✓ Modo VPN — usando IP da máquina")

    print()

    contas = []
    erros = 0
    session_idx = 0

    while len(contas) < qtd:
        # Modo VPN: session fake (sem proxy)
        if modo == "vpn":
            session = {"ip": "VPN"}
        else:
            if session_idx >= len(sessions):
                log("⚠ IPs acabaram, gerando mais...")
                novas = gerar_lista_ips(5)
                sessions.extend(novas)
                if session_idx >= len(sessions):
                    log("✗ Não conseguiu gerar mais IPs, esperando 30s...")
                    time.sleep(30)
                    continue
            session = sessions[session_idx]
            session_idx += 1

        tentativa = session_idx if modo == "proxy" else erros + len(contas) + 1

        print(f"\n{BOT_COR}{'─'*50}")
        log(f"CONTA {len(contas)+1}/{qtd} (tentativa {tentativa}) — IP: {session.get('ip', 'VPN')}")
        print(f"{'─'*50}\033[0m\n")

        sucesso, email, senha = criar_uma_conta(session, local_proxy)

        if sucesso and email:
            contas.append(f"{email}:{senha}")
            with open(ARQUIVO_SAIDA, "a", encoding="utf-8") as f:
                f.write(f"{email}:{senha}\n")
            _salvar_conta_db(email, senha, session.get("ip", "VPN"), bot_id, sucesso=True)
            log(f"💾 Salvo! ({len(contas)}/{qtd})")
        else:
            erros += 1
            _salvar_conta_db("FALHOU", "", session.get("ip", "VPN"), bot_id, sucesso=False)
            log(f"✗ Falhou — tentando de novo... ({len(contas)}/{qtd} criadas)")

        pausa = random.uniform(5, 10)
        log(f"Pausa {pausa:.0f}s...")
        time.sleep(pausa)

    if local_proxy:
        local_proxy.stop()

    print(f"\n{BOT_COR}{'='*50}")
    log(f"✅ BOT {bot_id} FINALIZADO!")
    log(f"   Criadas: {len(contas)}/{qtd} | Erros: {erros}")
    for c in contas:
        log(f"   {c}")
    print(f"{'='*50}\033[0m")
    print("\n  Pressione Enter...")
    input()


# ===================== LAUNCHER =====================

def launcher():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("\033[95m")
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║                                                      ║")
    print("  ║        DARKSAGE - Outlook Creator v22                ║")
    print("  ║                                                      ║")
    print("  ║   [1] VPN  — usa IP da sua VPN (sem proxy)         ║")
    print("  ║   [2] PROXY — proxy rotativo com IPs BR únicos     ║")
    print("  ║                                                      ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print("\033[0m")

    # Escolher modo
    while True:
        print("  \033[97mEscolha o modo:\033[0m")
        print("  \033[96m  [1]\033[0m VPN (sem proxy)")
        print("  \033[93m  [2]\033[0m PROXY (IPs BR únicos)")
        escolha = input("  → ").strip()
        if escolha in ["1", "2"]:
            break
        print("  \033[91mDigite 1 ou 2!\033[0m\n")

    modo = "vpn" if escolha == "1" else "proxy"
    print(f"\n  \033[92m✓ Modo: {modo.upper()}\033[0m\n")

    while True:
        try:
            print("  \033[97mQuantos emails TOTAL?\033[0m")
            qtd = int(input("  → ").strip())
            if qtd >= 1:
                break
        except ValueError:
            pass
        print("  \033[91mNúmero inválido!\033[0m\n")

    num_bots = min(2, qtd)
    contas_por_bot = [0] * num_bots
    for i in range(qtd):
        contas_por_bot[i % num_bots] += 1

    if modo == "proxy":
        total_ips = qtd * 2 + 6
        sessions = gerar_lista_ips(total_ips)
        if len(sessions) < qtd:
            print(f"\n  \033[91m⚠ Só conseguiu {len(sessions)} IPs\033[0m")
        bot_sessions = [[] for _ in range(num_bots)]
        for i, s in enumerate(sessions):
            bot_sessions[i % num_bots].append(s)
    else:
        # VPN: sem sessions, só meta
        bot_sessions = [[] for _ in range(num_bots)]

    print(f"\n  \033[93m⚡ Distribuição:\033[0m")
    for i in range(num_bots):
        if modo == "proxy":
            print(f"     BOT {i+1} → META: {contas_por_bot[i]} contas | {len(bot_sessions[i])} IPs")
        else:
            print(f"     BOT {i+1} → META: {contas_por_bot[i]} contas | VPN")
    print()

    script_path = os.path.abspath(__file__)

    for i in range(num_bots):
        if contas_por_bot[i] == 0:
            continue
        bot_id = i + 1
        payload = json.dumps({
            "sessions": bot_sessions[i],
            "meta": contas_por_bot[i],
            "modo": modo
        })

        temp_file = os.path.join(tempfile.gettempdir(), f"darksage_bot{bot_id}_sessions.json")
        with open(temp_file, "w") as f:
            f.write(payload)

        if os.name == 'nt':
            cmd = f'start /min "DARKSAGE BOT {bot_id}" cmd /k python "{script_path}" --bot {bot_id} --sessions-file "{temp_file}"'
            os.system(cmd)
        else:
            try:
                subprocess.Popen(["gnome-terminal", "--", "python3", script_path, "--bot", str(bot_id), "--sessions-file", temp_file])
            except:
                try:
                    subprocess.Popen(["xterm", "-e", f"python3 {script_path} --bot {bot_id} --sessions-file {temp_file}"])
                except:
                    subprocess.Popen(["python3", script_path, "--bot", str(bot_id), "--sessions-file", temp_file])

        print(f"  \033[92m✓ BOT {bot_id} lançado (meta: {contas_por_bot[i]} contas)\033[0m")
        time.sleep(5)

    print(f"\n  \033[92m✅ {num_bots} bots rodando!\033[0m")
    print("  Pressione Enter para sair...")
    input()


# ===================== MAIN =====================

def main():
    if "--bot" in sys.argv:
        try:
            bot_id = int(sys.argv[sys.argv.index("--bot") + 1])
            if "--sessions-file" in sys.argv:
                sf = sys.argv[sys.argv.index("--sessions-file") + 1]
                with open(sf, "r") as f:
                    sessions_json = f.read()
            elif "--sessions" in sys.argv:
                sessions_json = sys.argv[sys.argv.index("--sessions") + 1]
            else:
                print("Erro: --sessions-file ou --sessions necessário")
                sys.exit(1)
            rodar_bot(bot_id, sessions_json)
        except (IndexError, ValueError) as e:
            print(f"Erro: {e}")
            sys.exit(1)
    else:
        launcher()

if __name__ == "__main__":
    main()
