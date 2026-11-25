# SwipeVault — Threat Model & Security Controls

## Assets to Protect

1. **Vendor creative materials & provenance:** Authorized email swipes, PDFs, DOCX files, and ZIP packs stored in `/data/assets` and PostgreSQL.
2. **Operator workstation & browser session:** Admin session viewing untrusted HTML/document content extracted from third-party vendor files.
3. **Private LAN & Proxmox host environment:** Internal services (`127.0.0.1`, RFC1918 subnets, cloud metadata endpoints, local Listmonk/Proxmox APIs) must not be reachable via user-supplied source URLs.
4. **Recipient trust & compliance boundary:** Zero unintended campaign sends; no bypassing vendor approval gates or rate limits.

## Threats & Mitigations

| Threat | Vector | Mitigation Implemented |
|---|---|---|
| **Stored XSS via vendor HTML swipe** | Malicious `<script>`, `onload=`, `javascript:` link, or remote tracking pixel inside uploaded HTML/email body | Server-side `nh3` sanitization (`app/security/html.py`) strips scripts, event handlers, forms, iframes, and `<img>` tags; frontend renders HTML exclusively inside `<iframe sandbox="" srcdoc="...">` with `default-src 'none'; style-src 'unsafe-inline'; img-src data:`. |
| **SSRF / Internal network probing** | Offer or source URL pointing to `127.0.0.1`, `10.0.0.0/8`, `169.254.169.254`, `localhost`, `.local`, numeric IP encodings (`2130706433`), or non-HTTP ports | `app/security/urls.py` validates scheme (`http`/`https` only), rejects credentials, normalizes IDNA hostnames, blocks loopback/private/link-local/reserved IP literals (including decimal/hex notations) and local suffixes, and restricts ports to `80, 443, 8080, 8443`. Phase 2 fetcher also uses `resolve_and_check_host()` on every redirect hop. |
| **Archive traversal / Zip bomb / Malware upload** | ZIP with `../../etc/passwd`, symlinks, encrypted payloads, nested archives, >200:1 compression ratio, or `.exe`/macro-OLE disguised as `.pdf`/`.txt` | `app/security/filetypes.py` checks magic bytes alongside extension and blocks PE/ELF/Mach-O/shebang/OLE signatures. `app/adapters/extraction/archives.py` pre-validates the entire central directory (<=200 entries, <=100 MB expanded, <=25 MB per file, no `..`, no symlinks, compression ratio guard) before reading entries. |
| **Session hijacking / CSRF / Credential stuffing** | Cross-site POST to `/api/v1/*` or brute-force login attempts | Passwords hashed with Argon2id (`argon2-cffi`); raw session token stored only in `HttpOnly; SameSite=Lax` cookie (`sv_session`) with HMAC-SHA256 hash in PostgreSQL; double-submit CSRF cookie (`sv_csrf`) + `X-CSRF-Token` header required on all mutating endpoints; per-IP and per-account sliding-window login rate limiter. |
| **Container breakout / Exposed DB or queue** | Compromised parser process or public Postgres/Redis port | `postgres` and `redis` declare no host port bindings in `compose.yaml`; `api` and `worker` run as non-root `10001:10001` with no Docker socket access; `uvicorn --no-access-log` prevents query-string token leakage. |
| **Unverified compliance / health claims** | Aggressive vendor copy promising miracle cures or guaranteed results | Deterministic parser emits editorial review flags (`health_claim`, `guarantee_claim`, `income_claim`, `testimonial`, `missing_subject`, `placeholder_link`) and keeps all new or revised swipes in `pending` state until explicitly reviewed. |
