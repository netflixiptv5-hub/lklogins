# LKLOGINS - Sistema de Extração de Links/Códigos Streaming

## LINKS IMPORTANTES

| | |
|---|---|
| **Site produção** | https://lklogins-production.up.railway.app |
| **Repo GitHub** | https://github.com/netflixiptv5-hub/lklogins |
| **Branch** | master |
| **GitHub Token** | ver CREDENCIAIS.md |
| **Railway Token** | ver CREDENCIAIS.md |

## COMO FUNCIONA

1. Cliente digita email + serviço no site
2. Sistema tenta login via API Microsoft (2-3s)
3. Se falhar → Playwright browser (30s)
4. Se abuse/CAPTCHA → UC Chrome tenta resolver automaticamente
5. Retorna link ou código

## SERVIÇOS DISPONÍVEIS

| Serviço | ID |
|---|---|
| Redefinição Senha Netflix | `password_reset` |
| Atualização Residência Netflix | `household_update` |
| Código Temporário Netflix | `temp_code` |
| Desconectar Netflix | `netflix_disconnect` |
| Código Amazon Prime | `prime_code` |
| Código Disney+ | `disney_code` |
| Reset Globoplay | `globo_reset` |

## SENHAS PADRÃO

- **Hotmail/Outlook:** `02022013L` (alternativa: `A29b92c10@`)
- **Gmail (ck100k2):** `02022013L`
- **IMAP cinepremiu:** `02022013L@@@@`

## DEPLOY

Qualquer push no `master` → Railway rebuilda e sobe automaticamente.

```bash
git add -A
git commit -m "update"
git push
```

## BACKUP

Este repo É o backup. Sempre atualizado a cada mudança.
Última atualização: 08/04/2026
