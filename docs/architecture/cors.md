# Browser origins and CORS

Current code overrides this note. CORS controls browser access to responses; it
does not authenticate users or prevent non-browser requests. Telegram initData
validation remains mandatory on protected routes.

## Confirmed client flow

- `G:/webapp/src/api/client.ts`: relative requests by default; optional
  `VITE_API_URL` for a separate API origin. Auth uses `X-Telegram-Init-Data`, not
  cross-origin cookies. No `credentials: include` was found.
- `G:/webapp/vite.config.ts`: development port 5173 and `/api` proxy to port 8080.
- `G:/webapp/vercel.json`: `/api` rewrite to the configured backend. This backend
  destination is NOT proof of the frontend origin or current deployment state.
- `bot/api/app.py`: can serve the built Mini App on the same origin as the API.
- Localtunnel/Cloudflare scripts support changing tunnel addresses. Do not trust
  all subdomains of these providers or all Vercel previews.

The owner confirmed `https://ghos-web2.vercel.app` as the frontend and identified
`http://localhost:5173` as the local frontend (also matches Vite configuration).
These two origins are the defaults. The backend tunnel is a request destination,
not an additional trusted frontend. No preview origins have been confirmed.

## Configuration

`CORS_ALLOWED_ORIGINS` is a comma-separated list of exact browser origins:
scheme + host + optional port, without path, trailing slash, query or fragment.
Wildcards and embedded credentials are rejected. It replaces, rather than
extends, the default allowlist. Include each required additional development and
preview origin explicitly. Provider-wide wildcard trust is not supported.

If unset, the two confirmed defaults apply. An explicitly empty value denies
cross-origin access and emits a startup warning. There is no wildcard fallback.
Credentialed CORS is disabled in all cases.

Supported methods: GET, POST, PUT, DELETE, HEAD, OPTIONS. Headers:
Content-Type, X-Telegram-Init-Data, Bypass-Tunnel-Reminder plus middleware's
standard CORS-safelisted headers. Multipart replay upload remains supported.

## Owner activation checklist

1. The default list covers the confirmed frontend addresses. Verify any existing
   `CORS_ALLOWED_ORIGINS` override is intentional, especially an empty value.
2. If other preview/dev origins are needed, set the full list in that environment
   only after confirming `window.location.origin` (not the API destination).
3. Restart and check profile, settings, payment invoice opening, replay upload
   and evidence download in Telegram. No live payments are needed for this check.
4. Verify untrusted preflight is rejected and protected routes still require
   valid initData. Same-origin proxy requests do not require CORS permission.

No production environment settings were changed by this implementation.
Tests: `tests/test_cors.py`, `tests/test_auth.py` (fake identity and DB mocks).
