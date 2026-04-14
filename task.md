# LKLOGINS Fix — Verification Loop & Timeout

## Bugs found
1. **handle_verification codes accepted but MS loops** — after entering correct code, MS shows verification page AGAIN → system marks as failure → falls to code_login → tries 50 candidates × 120s each
2. **code_login ignores global timeout** — `_timed_out` is local to `process_job`, code_login thread keeps running for 10+ minutes after timeout
3. **50 recovery candidates** — way too many, wastes time on impossible matches

## Fixes applied
- [x] Added global `_cancelled_jobs` dict — timeout handler calls `_cancel_job(job_id)`
- [ ] Make `process_job_code_login` check `_is_job_cancelled()` before each candidate
- [ ] Limit candidates to max 5 in code_login
- [ ] After handle_verification succeeds with code but MS loops back → detect this as "MS rate limiting" and DON'T try code_login (it'll be same result)
- [ ] Set `_cancel_job` in timeout handler
- [ ] Clean up cancelled flag in finally block

## Files
- worker/rpa_worker.py — all changes here
