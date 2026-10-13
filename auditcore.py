"""ShelfReady Audit core: polite, public, SSRF-safe agent-readiness checks for a store domain (stdlib only)."""
import re, json, socket, ipaddress, time, urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor
UA = "ShelfReadyAudit/1.0 (+agent-readiness audit; public pages only)"
CLAUDE_UA = "Mozilla/5.0 (compatible; Claude-User/1.0; +Claude-User@anthropic.com)"
AI_BOTS = ["ClaudeBot", "Claude-User", "Claude-SearchBot", "GPTBot", "ChatGPT-User", "OAI-SearchBot", "PerplexityBot", "Google-Extended", "CCBot", "Meta-ExternalAgent", "Applebot-Extended"]
CLAUDE_BOTS = AI_BOTS[:3]
WALL = re.compile(r"cf-chl|challenge-platform|px-captcha|_Incapsula_|Pardon Our Interruption|Just a moment\.\.\.", re.I)
DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
class Blocked(Exception): pass
import os
# Dev sandboxes with fake-IP DNS (198.18.0.0/15) can opt in; never set this in production.
_FAKE = ipaddress.ip_network("198.18.0.0/15") if os.environ.get("SHELFREADY_DEV_ALLOW_FAKEIP") == "1" else None
def normalize(raw):
    s = (raw or "").strip().lower()
    s = re.sub(r"^[a-z]+://", "", s).split("/")[0].split("?")[0].split("#")[0].split(":")[0].strip(".")
    if s.startswith("www."): s = s[4:]
    if not DOMAIN_RE.match(s) or s.endswith((".local", ".internal", ".localhost", ".test", ".invalid", ".arpa")): raise ValueError("Enter a public store domain like allbirds.com")
    return s
def check_host(host):
    try: infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror: raise ValueError(f"{host} does not resolve")
    for i in infos:
        ip = ipaddress.ip_address(i[4][0].split("%")[0])
        if _FAKE and ip in _FAKE: continue
        if not ip.is_global or ip.is_multicast: raise Blocked(f"{host} resolves to a non-public address")
class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlparse(newurl)
        if u.scheme != "https" or (u.port not in (None, 443)): raise Blocked("redirect to non-https/port refused")
        check_host(u.hostname); return super().redirect_request(req, fp, code, msg, headers, newurl)
_opener = urllib.request.build_opener(SafeRedirect)
def fetch(url, ua=UA, timeout=6, method="GET", data=None, maxbytes=1_500_000):
    """Returns (status, text, headers, final_url). Never raises for HTTP errors."""
    u = urllib.parse.urlparse(url); check_host(u.hostname)
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": ua, "Accept": "text/html,application/json,*/*", **({"Content-Type": "application/json"} if data else {})})
    try:
        with _opener.open(req, timeout=timeout) as r: return r.status, r.read(maxbytes).decode("utf-8", "replace"), dict(r.headers), r.geturl()
    except urllib.error.HTTPError as e:
        try: body = e.read(200_000).decode("utf-8", "replace")
        except Exception: body = ""
        return e.code, body, dict(e.headers or {}), url
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as e:
        if isinstance(e, Blocked): raise
        return None, str(getattr(e, "reason", e))[:120], {}, url
def robots_rules(txt):
    groups, agents, rules = [], [], []
    for line in txt.splitlines():
        line = line.split("#")[0].strip()
        if ":" not in line: continue
        k, v = [x.strip() for x in line.split(":", 1)]; k = k.lower()
        if k == "user-agent":
            if rules: groups.append((agents, rules)); agents, rules = [], []
            agents.append(v.lower())
        elif k in ("allow", "disallow"): rules.append((k, v))
    if agents: groups.append((agents, rules))
    out = {}
    for b in AI_BOTS:
        for ags, rl in groups:
            if b.lower() in ags:
                out[b] = any(k == "disallow" and v == "/" for k, v in rl) and not any(k == "allow" and v == "/" for k, v in rl)
    return out
def edge_of(h):
    h = {k.lower(): v for k, v in h.items()}; s = h.get("server", "")
    if "cf-ray" in h or "cloudflare" in s.lower(): return "Cloudflare"
    if "vercel" in s.lower() or "x-vercel-id" in h: return "Vercel"
    if "cloudfront" in s.lower() or "x-amz-cf-id" in h: return "CloudFront"
    if "x-shopid" in h or "shopify" in s.lower(): return "Shopify"
    return s or "unknown"
def audit(raw, deadline_s=20):
    d = normalize(raw); t0 = time.time(); base = f"https://{d}"
    check_host(d)
    ex = ThreadPoolExecutor(8)
    f = {k: ex.submit(fetch, base + p) for k, p in {"robots": "/robots.txt", "pj": "/products.json?limit=3", "sitemap": "/sitemap.xml", "llms": "/llms.txt",
          "ucp": "/.well-known/ucp", "home": "/"}.items()}
    f["mcp"] = ex.submit(fetch, base + "/api/mcp", method="POST", data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode())
    left = lambda: max(1, deadline_s - (time.time() - t0))
    R = {k: (v.result(timeout=left()) if True else None) for k, v in f.items()}
    checks = []; ev = {}
    def add(cid, label, ok, evidence, pts, claude=0, na=False): checks.append({"id": cid, "label": label, "pass": ok, "na": na, "evidence": evidence, "points": pts if ok else 0, "max": pts, "claude_points": claude if ok else 0, "claude_max": claude})
    st, txt, _, _ = R["robots"]; rb = robots_rules(txt) if st == 200 else {}
    blocked = [b for b, v in rb.items() if v]; cblocked = [b for b in CLAUDE_BOTS if rb.get(b)]
    add("robots_ai", "robots.txt lets AI agents in", not blocked, f"HTTP {st}; " + (f"Disallow: / for {', '.join(blocked)}" if blocked else f"no Disallow: / for {len(AI_BOTS)} AI user agents"), 20)
    add("robots_claude", "robots.txt allows ClaudeBot, Claude-User, Claude-SearchBot", not cblocked, ("blocked: " + ", ".join(cblocked)) if cblocked else "not blocked", 0, 40)
    st, txt, _, _ = R["pj"]; prods = []
    try: prods = json.loads(txt).get("products", []) if st == 200 else []
    except ValueError: pass
    add("catalog", "Public machine-readable catalog (/products.json)", bool(prods), f"HTTP {st}; {len(prods)} products returned", 15)
    st, txt, _, _ = R["sitemap"]; add("sitemap", "sitemap.xml", st == 200 and "<" in txt[:300], f"HTTP {st}", 10)
    st, txt, _, _ = R["llms"]; ok = st == 200 and len(txt.strip()) > 20 and "<html" not in txt[:500].lower()
    add("llms", "llms.txt", ok, f"HTTP {st}" + (f"; first line: {txt.strip().splitlines()[0][:80]}" if ok else ""), 10)
    st, txt, _, _ = R["mcp"]; tools = []
    try: tools = [t["name"] for t in json.loads(txt).get("result", {}).get("tools", [])]
    except (ValueError, AttributeError, TypeError): pass
    add("mcp", "Agent tools via MCP (/api/mcp)", bool(tools), f"HTTP {st}; tools: {', '.join(tools) or 'none'}", 15, 30)
    add("mcp_shopping", "MCP exposes shopping tools (search/cart)", any(re.search(r"search_(shop_)?catalog|product|cart", t) and "polic" not in t for t in tools), f"{len(tools)} tool(s): {', '.join(tools) or 'none'}", 0)
    st, txt, _, _ = R["ucp"]; add("ucp", "/.well-known/ucp (Universal Commerce Protocol)", st == 200 and txt.strip().startswith("{"), f"HTTP {st}", 0)
    edge = edge_of(R["home"][2])
    pp = None
    if prods:
        u = f"{base}/products/{prods[0]['handle']}"
        g = ex.submit(fetch, u); c = ex.submit(fetch, u, CLAUDE_UA)
        pst, ptxt, ph, _ = g.result(timeout=left()); cst, ctxt, ch, _ = c.result(timeout=left()); pp = u
        if ph: edge = edge_of(ph)
        wall = pst in (403, 429, 503) or bool(pst != 200 and WALL.search(ptxt[:20000]))
        add("no_wall", "Product page reachable (no bot wall)", not wall, f"{u} → HTTP {pst}", 15)
        j = " ".join(re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', ptxt, re.S | re.I))
        jp = bool(re.search(r'"@type"\s*:\s*\[?\s*"(Product|ProductGroup)"', j))
        add("jsonld", "schema.org Product JSON-LD", jp, "found Product/ProductGroup" if jp else "no Product JSON-LD in page", 10)
        jo = bool(re.search(r'"price"\s*:', j)) and bool(re.search(r"availability", j, re.I))
        add("jsonld_offer", "JSON-LD price + availability", jo, "price & availability present" if jo else "missing price or availability", 5)
        import html as _h
        readable = cst == 200 and prods[0]["title"][:15].lower() in _h.unescape(ctxt).lower()
        add("claude_fetch", "Readable by Claude's web fetch (Claude-User UA)", readable, f"HTTP {cst} with Claude-User UA vs HTTP {pst} with audit UA", 0, 30)
        ev["claude_fetch_status"] = str(cst)
    else:
        for cid, lab, pts, cp in [("no_wall", "Product page reachable (no bot wall)", 15, 0), ("jsonld", "schema.org Product JSON-LD", 10, 0), ("jsonld_offer", "JSON-LD price + availability", 5, 0), ("claude_fetch", "Readable by Claude's web fetch (Claude-User UA)", 0, 30)]:
            add(cid, lab, False, "not checked: no public catalog to find a product page", pts, cp, na=True)
        ev["claude_fetch_status"] = "n/a"
    ex.shutdown(wait=False, cancel_futures=True)
    score = sum(c["points"] for c in checks); cscore = sum(c["claude_points"] for c in checks)
    by = {c["id"]: c for c in checks}
    row = {"domain": d, "score": str(score), "claude_score": str(cscore), "claude_fetch_status": ev["claude_fetch_status"], "claude_fetch_readable": str(by["claude_fetch"]["pass"]),
           "products_json": f"{R['pj'][0] if R['pj'][0] else 'ERR'}/{len(prods)}", "jsonld_product": str(by["jsonld"]["pass"]), "llms_txt": str(by["llms"]["pass"]),
           "storefront_mcp_tools": str(len(tools)), "product_page": "n/a" if not prods else "200"}
    return {"domain": d, "score": score, "claude_score": cscore, "edge": edge, "product_page": pp, "checks": checks, "row": row,
            "top_issue": top_issue(checks), "audited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "elapsed_s": round(time.time() - t0, 1)}
PRIORITY = ["claude_fetch", "no_wall", "robots_claude", "robots_ai", "catalog", "jsonld", "mcp", "llms", "jsonld_offer", "sitemap", "mcp_shopping"]
SHORT = {"claude_fetch": "blocks Claude's web fetch", "no_wall": "product pages sit behind a bot wall", "robots_claude": "robots.txt blocks Claude",
         "robots_ai": "robots.txt blocks AI agents", "catalog": "no public machine-readable catalog", "jsonld": "no schema.org Product markup",
         "mcp": "no agent (MCP) endpoint", "llms": "no llms.txt", "jsonld_offer": "markup missing price/stock", "sitemap": "no sitemap",
         "mcp_shopping": "agents can read policies but can't search or cart"}
def top_issue(checks):
    by = {c["id"]: c for c in checks}
    for k in PRIORITY:
        c = by.get(k)
        if c and not c["pass"] and not c["na"]: return SHORT[k]
    for k in PRIORITY:
        c = by.get(k)
        if c and not c["pass"]: return SHORT[k]
    return "fully agent-ready"
