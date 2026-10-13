# ShelfReady Audit

Free, self-serve **agent-readiness audit** for online stores. It answers: *can AI agents like Claude, Grok and Muse find, read and buy from this store?*
Enter a domain to get an overall score, a Claude-readiness score, pass/fail checks with evidence, and an auto-generated fix kit. Each report has a shareable URL: `/r/<domain>`.

Single Python file server, **standard library only** (Python 3.10+). No database, no dependencies.

## Score (one headline number, 0-100)
| Category | Max | Checks (points) |
|-|-|-|
| Agent can shop | 35 | public catalog feed `/products.json` (15) · MCP endpoint (5) · MCP has shopping tools such as search/cart (15). A policy-only MCP caps this at 20 |
| Claude/AI fetch not blocked | 25 | product page reachable, no bot wall (10) · product page readable with a Claude-User UA (15) |
| Structured product data | 20 | schema.org Product JSON-LD (12) · price + availability (8) |
| robots.txt | 10 | no `Disallow: /` for 11 AI agents (5) · ClaudeBot/Claude-User/Claude-SearchBot allowed (5) |
| Discovery | 10 | llms.txt (4) · `/.well-known/ucp` (3) · sitemap.xml (3) |
Category sub-scores are shown on every report. Oct 13 2026 run on 25 Shopify DTC brands: median 85, range 10-85. Nobody hits 100 because no store exposed public search/cart agent tools.
The Claude-User test spoofs only the user-agent string. Claude's real requests come from Anthropic IPs, so treat a 403 as "your bot rules key on this UA", not proof that Claude is blocked.

## Routes
`/` landing · `/install?store=` merchant onboarding · `/audit?store=` → redirect · `/r/<domain>` report (HTML, OG/Twitter card) · `/api/audit?store=` JSON · `/og.png` · `/healthz`

## Safety and politeness
- Public pages only: about 9 GETs and 1 JSON-RPC `tools/list` POST per audit. 6s per request, ~20s total budget. Identifies itself as `ShelfReadyAudit/1.0`.
- Domain validation, plus **SSRF protection**: every host, including redirect targets, must resolve only to global IPs. HTTPS on port 443 only.
- Per-IP limit of 10 new audits/hour (`RATE_LIMIT_PER_HOUR`). Results are cached 24h (`CACHE_TTL_S`), and cached reports are never rate-limited. At most 4 audits run concurrently.
- Strict CSP, all output HTML-escaped, no request logging.
- Known limit: the DNS check and the connection resolve separately, so a fast DNS rebind is theoretically possible. If you need stronger isolation, run behind an egress firewall that denies private ranges.

## Run / deploy
```
python3 app.py                 # http://localhost:8080
python3 test_app.py            # unit + server tests (offline)
SHELFREADY_LIVE=1 python3 test_app.py   # + live network test
```
Render: New → Blueprint → this repo (`render.yaml`, free plan, health check `/healthz`). Set `PUBLIC_BASE_URL`.

## Reply helper (prints lines; never posts)
```
python3 replies.py --base https://shelfready-audit.onrender.com @Ridge:ridge.com @bombas:bombas.com
python3 replies.py --base URL --api --file stores.txt    # uses the deployed /api/audit
```
Output: `@Ridge Ridge scored 70/100 on agent-readiness: blocks Claude's web fetch. Full report: …/r/ridge.com` (always ≤280 chars).

## ShelfReady
Want agents to actually shop your store? ShelfReady is an MCP connector with product search, live variants and stock, and cart links the shopper checks out with on your site. We also offer done-for-you fixes. Contact: kylebauer@mail.grokbot.com
