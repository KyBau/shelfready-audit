# ShelfReady Audit

Free, self-serve **agent-readiness audit** for online stores. It answers: *can AI agents like Claude, Grok and Muse find, read and buy from this store?*
Enter a domain to get an overall score, a Claude-readiness score, pass/fail checks with evidence, and an auto-generated fix kit. Each report has a shareable URL: `/r/<domain>`.

Single Python file server, **standard library only** (Python 3.10+). No database, no dependencies.

## Checks
| Check | Points | Claude pts |
|-|-|-|
| robots.txt has no `Disallow: /` for 11 AI user agents | 20 | |
| robots.txt allows ClaudeBot / Claude-User / Claude-SearchBot | | 40 |
| Public machine-readable catalog (`/products.json`) | 15 | |
| `sitemap.xml` | 10 | |
| Product page reachable (no bot wall) | 15 | |
| schema.org Product JSON-LD / price + availability | 10 / 5 | |
| `llms.txt` | 10 | |
| MCP agent endpoint (`/api/mcp` tools/list) | 15 | 30 |
| Product page readable with a Claude-User UA | | 30 |
| Info only: MCP exposes shopping tools, `/.well-known/ucp` | 0 | |
The Claude-User test spoofs only the user-agent string. Claude's real requests come from Anthropic IPs, so treat a 403 as "your bot rules key on this UA", not proof that Claude is blocked.

## Routes
`/` landing · `/audit?store=` → redirect · `/r/<domain>` report (HTML, OG/Twitter card) · `/api/audit?store=` JSON · `/og.png` · `/healthz`

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
Output: `@Ridge Ridge scored 100/100 (Claude: 70/100) on agent-readiness — blocks Claude's web fetch. Full report: …/r/ridge.com` (always ≤280 chars).

## ShelfReady
Want agents to actually shop your store? ShelfReady is an MCP connector with product search, live variants and stock, and cart links the shopper checks out with on your site. We also offer done-for-you fixes. Contact: kylebauer@mail.grokbot.com
