#!/usr/bin/env python3
"""ShelfReady Audit: self-serve agent-readiness audit for online stores. Stdlib only (Python 3.10+).
Routes: /  ·  /audit?store=  ·  /r/<domain>  ·  /api/audit?store=  ·  /og.png  ·  /healthz"""
import os, re, json, time, base64, html, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import auditcore, fixkit
from og_png import OG_PNG_B64
VERSION = "1.1.0"
BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
CONTACT = os.environ.get("CONTACT_EMAIL", "kylebauer@mail.grokbot.com")
RATE_PER_HOUR = int(os.environ.get("RATE_LIMIT_PER_HOUR", "10"))
CACHE_TTL = int(os.environ.get("CACHE_TTL_S", str(24 * 3600)))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT_AUDITS", "4"))
OG_PNG = base64.b64decode("".join(OG_PNG_B64))
_cache, _hits, _lock = {}, {}, threading.Lock()
_sem = threading.BoundedSemaphore(MAX_CONCURRENT)
class RateLimited(Exception): pass
def cached(domain):
    with _lock:
        c = _cache.get(domain)
        return c[1] if c and time.time() - c[0] < CACHE_TTL else None
def take_token(ip):
    now = time.time()
    with _lock:
        h = [t for t in _hits.get(ip, []) if now - t < 3600]
        if len(h) >= RATE_PER_HOUR: _hits[ip] = h; raise RateLimited(f"Rate limit: {RATE_PER_HOUR} new audits per hour. Cached reports are always free to view.")
        h.append(now); _hits[ip] = h
        if len(_hits) > 50_000: _hits.clear()
def run_audit(raw, ip, fresh_ok=True):
    d = auditcore.normalize(raw)
    r = cached(d)
    if r: return r
    if not fresh_ok: return None
    take_token(ip)
    if not _sem.acquire(timeout=10): raise RateLimited("Server busy, try again in a minute.")
    try: r = auditcore.audit(d, deadline_s=20)
    finally: _sem.release()
    kit_md = fixkit.kit(r["row"], r["edge"], "products").replace("2026-10-13 (agent_readiness)", r["audited_at"][:10])
    r["fix_kit_markdown"] = kit_md
    with _lock:
        _cache[d] = (time.time(), r)
        if len(_cache) > 5000: _cache.pop(next(iter(_cache)))
    return r
def base_url(h):
    if BASE_URL: return BASE_URL
    host = re.sub(r"[^a-zA-Z0-9.:-]", "", h.get("Host", "localhost"))
    return ("https://" if h.get("X-Forwarded-Proto") == "https" else "http://") + host
E = html.escape
CSS = """*{box-sizing:border-box}body{margin:0;background:#0f1115;color:#e6edf3;font:16px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'DejaVu Sans',sans-serif}
a{color:#7ee787}.w{max-width:860px;margin:0 auto;padding:24px 18px 60px}h1{color:#7ee787;font-size:30px;margin:8px 0}h2{font-size:20px;margin:32px 0 10px}
.sub{color:#8b949e}.card{background:#161b22;border:1px solid #30363d;border-radius:14px;padding:18px;margin:14px 0}
form{display:flex;gap:10px;flex-wrap:wrap}input{flex:1;min-width:200px;padding:14px;border-radius:10px;border:1px solid #30363d;background:#0d1117;color:#e6edf3;font-size:17px}
button,.btn{padding:14px 20px;border:0;border-radius:10px;background:#238636;color:#fff;font-weight:700;font-size:16px;cursor:pointer;text-decoration:none;display:inline-block}
.scores{display:flex;gap:14px;flex-wrap:wrap}.score{flex:1;min-width:160px;text-align:center;border-radius:14px;padding:18px;background:#11261a;border:2px solid #7ee787}
.score b{display:block;font-size:44px;line-height:1.1}.mid{background:#272115;border-color:#d29922}.mid b{color:#d29922}.lo{background:#2a1416;border-color:#f85149}.lo b{color:#f85149}.hi b{color:#7ee787}
.chk{display:flex;gap:12px;padding:12px 0;border-top:1px solid #21262d}.chk:first-child{border-top:0}.dot{flex:0 0 26px;height:26px;border-radius:7px;text-align:center;font-weight:700;line-height:26px}
.p{background:#238636}.f{background:#da3633}.n{background:#30363d;color:#8b949e}.ev{color:#8b949e;font-size:14px;word-break:break-word}.pts{margin-left:auto;color:#8b949e;font-size:14px;white-space:nowrap}
pre{background:#0d1117;border:1px solid #30363d;border-radius:10px;padding:14px;overflow:auto;font-size:13px;white-space:pre-wrap;word-break:break-word}
.cta{background:#1f6feb;border-radius:14px;padding:20px;margin-top:28px}.cta a{color:#fff;font-weight:700}.err{background:#2a1416;border:1px solid #f85149;border-radius:10px;padding:12px}
.sub2{display:flex;flex-wrap:wrap;justify-content:space-between;margin:8px 0}.bar{flex-basis:100%;height:8px;background:#21262d;border-radius:4px;margin-top:4px}.bar i{display:block;height:8px;border-radius:4px}.bar i.hi{background:#3fb950}.bar i.mid{background:#d29922}.bar i.lo{background:#f85149}
footer{color:#6e7681;font-size:13px;margin-top:40px}"""
def page(title, desc, body, url, base):
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{E(title)}</title><meta name=description content="{E(desc)}">
<meta property=og:type content=website><meta property=og:title content="{E(title)}"><meta property=og:description content="{E(desc)}">
<meta property=og:url content="{E(url)}"><meta property=og:image content="{E(base)}/og.png"><meta property=og:image:width content=1200><meta property=og:image:height content=630>
<meta name=twitter:card content=summary_large_image><meta name=twitter:title content="{E(title)}"><meta name=twitter:description content="{E(desc)}"><meta name=twitter:image content="{E(base)}/og.png">
<style>{CSS}</style></head><body><div class=w>{body}<footer>ShelfReady Audit v{VERSION} · public, read-only checks of each store's own pages · not affiliated with Anthropic, Shopify or any store audited ·
user-agent "ShelfReadyAudit/1.0" plus one request with a Claude-User user-agent to test bot rules.</footer></div></body></html>"""
FORM = """<form action=/audit method=get><input name=store placeholder="yourstore.com" autocomplete=off autocapitalize=off required maxlength=253 value="{v}"><button>Run audit</button></form>"""
def landing(base, err="", v=""):
    b = f"""<h1>ShelfReady Audit</h1><p class=sub>Can AI agents like Claude, Grok and Muse find, read and buy from your store? About 10 public checks, a score in seconds, and a fix kit.</p>
<div class=card>{FORM.format(v=E(v))}{f'<p class=err>{E(err)}</p>' if err else ''}</div>
<div class=card><b>What we check</b><ul class=sub><li>robots.txt rules for ClaudeBot, Claude-User, Claude-SearchBot, GPTBot and more</li><li>Bot walls: does a product page answer a Claude-User request?</li>
<li>Machine-readable catalog, sitemap, schema.org Product markup with price and stock</li><li>llms.txt, MCP agent tools, /.well-known/ucp</li></ul></div><p class=sub>Merchants: <a href=/install>get your own ShelfReady connector →</a></p>"""
    return page("ShelfReady Audit: is your store agent-ready?", "Free agent-readiness score for any store: Claude, Grok and Muse access, bot walls, product markup, MCP. With a fix kit.", b, base + "/", base)
CONNECTOR_REPO = os.environ.get("CONNECTOR_REPO_URL", "https://github.com/KyBau/shelfready")
def install_page(base, store=""):
    d = ""
    try: d = auditcore.normalize(store) if store else ""
    except ValueError: d = ""
    name = d.split(".")[0].replace("-", " ").title() if d else "Your Store"; dom = d or "yourstore.com"
    b = f"""<p><a href=/>← ShelfReady Audit</a></p><h1>Get your store's ShelfReady connector</h1>
<p class=sub>One URL that lets Claude, Grok and Muse search {E(name)}'s catalog, check live sizes and stock, and hand shoppers a cart link they check out with on your site. Read-only. No payments, no orders placed by the agent.</p>
<div class=card><form action=/install method=get><input name=store placeholder="yourstore.com" value="{E(d)}" maxlength=253><button>Preview my setup</button></form></div>
<h2>How it works</h2><div class=card><ol>
<li><b>Run the free audit.</b> <a href="/r/{E(dom)}">/r/{E(dom)}</a> shows what blocks agents today, plus a fix kit (CDN rule, product markup, llms.txt).</li>
<li><b>We set up your connector</b>, locked to <b>{E(dom)}</b> and branded "Official {E(name)} shopping tool". Optionally limited to chosen collections.<br>
Your connector URL: <code>https://{E(dom.split('.')[0])}.shelfready.app/mcp</code> <span class=sub>(illustrative; issued at setup)</span></li>
<li><b>Agents shop, you get attribution.</b> Every cart link is tagged <code>?ref=shelfready&amp;utm_source=shelfready&amp;utm_medium=ai_agent</code>, so agent-originated orders show up in Shopify analytics.</li>
<li><b>We list it</b> in Claude's connector directory, Grok custom connectors and Muse, and add it to your llms.txt.</li></ol></div>
<h2>Tools your connector exposes</h2><div class=card><ul class=sub>
<li><b>search_products</b>: query plus price, type and in-stock filters</li><li><b>get_product</b>: variants, sizes, price, compare-at price, stock</li>
<li><b>build_cart_link</b>: validated cart permalink with attribution; the shopper checks out on your site</li><li><b>get_policies</b>: returns, shipping, privacy, terms</li></ul></div>
<h2>Self-host instead (free, open source)</h2><div class=card><pre>SHELFREADY_STORE={E(dom)}
SHELFREADY_STORE_NAME={E(name)}
SHELFREADY_ALLOW_ANY_STORE=0
SHELFREADY_COLLECTIONS=          # optional, e.g. mens-shoes,new-arrivals
SHELFREADY_REF=shelfready
# Render: New → Blueprint → {E(CONNECTOR_REPO)}  ·  health check /healthz  ·  MCP endpoint POST /mcp</pre></div>
<div class=cta><b>Want it hosted and listed for you?</b><br>Email <a href="mailto:{E(CONTACT)}?subject={urllib.parse.quote('ShelfReady connector for ' + dom)}">{E(CONTACT)}</a> with your store domain.</div>
<p class=sub>Requirements: a Shopify store whose /products.json is public (most are). Headless storefronts: see your audit's fix kit first.</p>"""
    return page(f"ShelfReady connector for {name}", f"Let Claude, Grok and Muse shop {dom}: search, live stock, attributed cart links.", b, f"{base}/install", base)
def cls(n, mx=100): return "hi" if n >= .85 * mx else ("mid" if n >= .5 * mx else "lo")
def report(r, base):
    d = r["domain"]; url = f"{base}/r/{d}"
    rows = "".join(f"""<div class=chk><div class="dot {'n' if c['na'] else ('p' if c['pass'] else 'f')}">{'–' if c['na'] else ('✓' if c['pass'] else '✗')}</div>
<div><b>{E(c['label'])}</b><div class=ev>{E(c['evidence'])}</div></div><div class=pts>{c['points']}/{c['max']}</div></div>""" for c in r["checks"])
    b = f"""<p><a href=/>← ShelfReady Audit</a></p><h1>{E(d)}</h1><p class=sub>Audited {E(r['audited_at'])} · edge: {E(r['edge'])} · took {r['elapsed_s']}s · top issue: <b>{E(r['top_issue'])}</b></p>
<div class=scores><div class="score {cls(r['score'])}"><b>{r['score']}</b>ShelfReady score /100</div></div>
<div class=card>{"".join(f"<div class=sub2><span>{E(s['label'])}</span><span>{s['score']}/{s['max']}</span><div class=bar><i class={cls(s['score'], s['max'])} style='width:{round(100*s['score']/s['max'])}%'></i></div></div>" for s in r['subscores'].values())}</div>
<h2>Checks</h2><div class=card>{rows}</div>
<h2>Your fix kit</h2><p class=sub>Generated from the failed checks. Review before applying, and verify field names in your CDN dashboard.</p><pre>{E(r['fix_kit_markdown'])}</pre>
<div class=cta><b>Want agents to actually shop your store?</b><br>ShelfReady gives Claude, Grok and Muse real tools: product search, live variants and stock, and a cart link the shopper checks out with on your site. We can also apply this fix kit for you.<br><br>
<a href="/install?store={E(d)}">Get your connector →</a> · <a href="mailto:{E(CONTACT)}?subject={urllib.parse.quote('ShelfReady for ' + d)}">Email {E(CONTACT)}</a></div>
<h2>Audit another store</h2><div class=card>{FORM.format(v='')}</div><p class=sub>Share: <a href="{E(url)}">{E(url)}</a> · JSON: <a href="/api/audit?store={E(d)}">/api/audit?store={E(d)}</a></p>"""
    return page(f"{d} scored {r['score']}/100 on agent-readiness · ShelfReady", f"Top issue: {r['top_issue']}. Free audit + fix kit.", b, url, base)
class H(BaseHTTPRequestHandler):
    server_version = "shelfready-audit/" + VERSION
    def log_message(self, *a): pass
    def ip(self):
        xf = self.headers.get("X-Forwarded-For") if os.environ.get("TRUST_PROXY", "1") == "1" else None
        return (xf.split(",")[0].strip() if xf else self.client_address[0])
    def send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)
    def do_HEAD(self): self.do_GET()
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query); base = base_url(self.headers); store = (q.get("store") or [""])[0][:300]
        try:
            if u.path == "/healthz": return self.send(200, json.dumps({"ok": True, "version": VERSION, "cached": len(_cache)}), "application/json")
            if u.path == "/og.png": return self.send(200, OG_PNG, "image/png", {"Cache-Control": "public, max-age=86400"})
            if u.path == "/robots.txt": return self.send(200, "User-agent: *\nAllow: /\n", "text/plain")
            if u.path == "/": return self.send(200, landing(base))
            if u.path == "/install": return self.send(200, install_page(base, store))
            if u.path == "/audit":
                try: d = auditcore.normalize(store)
                except ValueError as e: return self.send(400, landing(base, str(e), store))
                return self.send(303, "", extra={"Location": f"/r/{d}"})
            if u.path.startswith("/r/"):
                raw = urllib.parse.unquote(u.path[3:])
                try:
                    d = auditcore.normalize(raw)
                    if d != raw: return self.send(301, "", extra={"Location": f"/r/{d}"})
                    r = run_audit(d, self.ip())
                except (ValueError, auditcore.Blocked) as e: return self.send(400, landing(base, str(e), raw))
                except RateLimited as e: return self.send(429, landing(base, str(e), raw), extra={"Retry-After": "3600"})
                return self.send(200, report(r, base), extra={"Cache-Control": "public, max-age=600"})
            if u.path == "/api/audit":
                try: r = run_audit(store, self.ip())
                except (ValueError, auditcore.Blocked) as e: return self.send(400, json.dumps({"error": str(e)}), "application/json")
                except RateLimited as e: return self.send(429, json.dumps({"error": str(e)}), "application/json", {"Retry-After": "3600"})
                out = {k: v for k, v in r.items() if k != "row"}; out["report_url"] = f"{base}/r/{r['domain']}"
                return self.send(200, json.dumps(out, indent=1), "application/json", {"Access-Control-Allow-Origin": "*"})
            self.send(404, landing(base, "Page not found."))
        except Exception:
            self.send(500, landing(base, "Something went wrong running that audit. Try again shortly."))
def main():
    port = int(os.environ.get("PORT", "8080")); host = os.environ.get("HOST", "0.0.0.0")
    print(f"ShelfReady Audit on http://{host}:{port}", flush=True); ThreadingHTTPServer((host, port), H).serve_forever()
if __name__ == "__main__": main()
