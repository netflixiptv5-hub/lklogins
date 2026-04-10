# Task: CAPTCHA Solver para LKLogins

## Diagnóstico dos logs (job a5ftw8vhb7pmns90bs6)
1. UC login OK, chegou na abuse page OK
2. Clicou "Next" OK
3. iframe hsprotect.net encontrado mas **size=0x0**
4. _find_captcha_iframe retornou None (exige width > 50)
5. Na tentativa 2, Chrome crashou (Connection refused port 44029)

## Diferença DARKSAGE vs captcha_solver.py
- DARKSAGE: roda no Windows com display real, iframe renderiza width > 50
- captcha_solver.py: roda no Railway (Linux) com Xvfb, iframe fica 0x0
- O `resolver_pressione_segure` do DARKSAGE é identico em lógica
- A diferença é o AMBIENTE, não o código

## Ideia do usuário
Fazer um serviço EXTERNO (micro-API) que roda numa máquina com display real
O lklogins manda sinal → serviço externo resolve → devolve resultado

## Plano: Adaptar DARKSAGE como micro-API de CAPTCHA
1. Criar `captcha_service.py` — Flask/FastAPI que expõe endpoint POST /solve
2. Recebe: email, password, abuse_url
3. Abre UC Chrome local (máquina do user com display real)
4. Faz login → resolve CAPTCHA → retorna {solved: true/false}
5. No lklogins, quando abuse, chama esse serviço externo via HTTP
