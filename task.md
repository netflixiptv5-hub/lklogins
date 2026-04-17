# DIAGNÓSTICO: josemonteiro11112001@hotmail.com — netflix_disconnect

## Problema Identificado
A conta tem recovery email mascarado como `ne*****@cinepremiu.com`.
O código resolve isso como `ne@cinepremiu.com` — ERRADO.

### Fluxo completo que aconteceu:
1. API login → "verification_needed" → fallback browser
2. Playwright login OK → MS pede verificação (identity/confirm)
3. MS mostra email mascarado: `ne*****@cinepremiu.com`
4. Sistema tenta resolver: vê prefixo "ne" ≠ username "josemonteiro11112001"
5. **GUESS: `ne@cinepremiu.com`** ← ERRADO
6. Manda código pra `ne@cinepremiu.com` → não chega (email errado)
7. Tenta `josemonteiro11112001@cinepremiu.com` → MS rejeita (wrong recovery)
8. Tenta `catchall@cinepremiu.com` → MS rejeita
9. Loop retry → mesma coisa
10. Fallback code_login → gera candidatos:
    - `josemonteiro11112001@cinepremiu.com` → wrong
    - `netflix@cinepremiu.com` → **CODE SENT!** ← esse era o certo mas servidor reiniciou antes de ler

## O REAL recovery email é: `netflix@cinepremiu.com`
- O mascarado `ne*****@cinepremiu.com` = `netflix@cinepremiu.com` (7 chars: n-e-t-f-l-i-x)
- Mas o code_login adivinha certo (tenta netflix@cinepremiu.com) e funciona!

## Problemas no código:
1. Na resolução de masked email (handle_verification), quando prefix='ne' e domain='cinepremiu.com':
   - Ele faz `guess = prefix + "@" + domain` = `ne@cinepremiu.com` 
   - Deveria tentar KNOWN patterns como netflix@, netflix1@, etc
   
2. O code_login TEM a lista certa de candidatos (line 57 dos logs):
   `['josemonteiro11112001@cinepremiu.com', 'netflix@cinepremiu.com', 'netflix1@cinepremiu.com', 'netflix2@cinepremiu.com', 'netflix3@cinepremiu.com']`
   E `netflix@cinepremiu.com` FUNCIONA (log 62-63: "Code sent!")

3. Mas o servidor REINICIOU antes de completar o code_login

## Fix necessário:
Na função de resolução de masked email, adicionar `netflix@cinepremiu.com` (e variantes) 
como candidatos conhecidos no KNOWN_RECOVERY_EMAILS.

Também: na primeira tentativa (handle_verification Flow A), já deveria tentar `netflix@cinepremiu.com` 
em vez de `ne@cinepremiu.com` quando o masked hint começa com "ne" e domain é cinepremiu.com.
