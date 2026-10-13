import os, json, socket, threading, unittest, urllib.request, urllib.error
from unittest import mock
import auditcore, app, replies
LIVE = os.environ.get("SHELFREADY_LIVE") == "1"
FAKE = {"domain": "example-store.com", "score": 70, "subscores": {"shop": {"label": "Agent can shop", "score": 20, "max": 35}, "access": {"label": "Claude/AI fetch not blocked", "score": 10, "max": 25}}, "claude_score": 70, "edge": "Cloudflare", "product_page": "https://example-store.com/products/x",
        "checks": [{"id": "claude_fetch", "label": "Readable by Claude's web fetch", "pass": False, "na": False, "evidence": "HTTP 403 with Claude-User UA vs HTTP 200", "points": 0, "max": 0, "claude_points": 0, "claude_max": 30},
                   {"id": "jsonld", "label": "schema.org Product JSON-LD", "pass": True, "na": False, "evidence": "<script>alert(1)</script>", "points": 10, "max": 10, "claude_points": 0, "claude_max": 0}],
        "row": {"domain": "example-store.com", "score": "85", "claude_score": "70", "claude_fetch_status": "403", "claude_fetch_readable": "False", "products_json": "200/3",
                "jsonld_product": "True", "llms_txt": "True", "storefront_mcp_tools": "1", "product_page": "200"},
        "top_issue": "blocks Claude's web fetch", "audited_at": "2026-10-13T06:50:00Z", "elapsed_s": 1.2}
def addr(ip): return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]
class Validation(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(auditcore.normalize("https://www.Allbirds.com/products/x?y=1"), "allbirds.com")
        for bad in ["localhost", "127.0.0.1", "foo", "a b.com", "x.local", "http://[::1]/", "169.254.169.254", "evil.internal", ""]:
            with self.assertRaises(ValueError, msg=bad): auditcore.normalize(bad)
    def test_private_ips_blocked(self):
        for ip in ["10.0.0.1", "127.0.0.1", "169.254.169.254", "192.168.1.1", "172.16.0.5", "100.64.0.1", "::1", "fd00::1", "0.0.0.0"]:
            with mock.patch("socket.getaddrinfo", return_value=addr(ip)), self.assertRaises(auditcore.Blocked, msg=ip): auditcore.check_host("rebind.example.com")
        with mock.patch("socket.getaddrinfo", return_value=addr("23.227.38.65")): auditcore.check_host("shop.example.com")
    def test_redirect_to_private_refused(self):
        h = auditcore.SafeRedirect()
        with mock.patch("socket.getaddrinfo", return_value=addr("10.1.2.3")), self.assertRaises(auditcore.Blocked):
            h.redirect_request(urllib.request.Request("https://a.com/"), None, 302, "", {}, "https://internal.example.com/")
        with self.assertRaises(auditcore.Blocked): h.redirect_request(urllib.request.Request("https://a.com/"), None, 302, "", {}, "http://a.com:8080/")
    def test_robots(self):
        r = auditcore.robots_rules("User-agent: ClaudeBot\nDisallow: /\n\nUser-agent: GPTBot\nDisallow: /cart\n")
        self.assertTrue(r["ClaudeBot"]); self.assertFalse(r["GPTBot"])
    def test_weights(self):
        self.assertEqual(sum(auditcore.CAT_MAX.values()), 100)
        self.assertLessEqual(auditcore.WEIGHTS["mcp"][1] + auditcore.WEIGHTS["catalog"][1], 20)  # policy-only MCP + feed caps the shop category at 20/35
    def test_top_issue(self): self.assertEqual(auditcore.top_issue(FAKE["checks"]), "blocks Claude's web fetch")
class Replies(unittest.TestCase):
    def test_line(self):
        s = replies.line("@ridge", "ridge.com", 100, "blocks Claude's web fetch", "https://x.onrender.com")
        self.assertEqual(s, "@ridge Ridge scored 100/100 on agent-readiness: blocks Claude's web fetch. Full report: https://x.onrender.com/r/ridge.com")
        self.assertLessEqual(len(replies.line("@" + "a" * 15, "a" * 60 + ".com", 5, "x" * 200, "https://" + "b" * 40)), 280)
class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = app.ThreadingHTTPServer(("127.0.0.1", 0), app.H); threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()
    def setUp(self): app._cache.clear(); app._hits.clear()
    def get(self, p, headers=None):
        class NoRedir(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a): return None
        try:
            r = urllib.request.build_opener(NoRedir).open(urllib.request.Request(self.base + p, headers=headers or {}), timeout=10); return r.status, r.read().decode("utf-8", "replace"), r.headers
        except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8", "replace"), e.headers
    def test_landing_and_meta(self):
        st, b, _ = self.get("/"); self.assertEqual(st, 200); self.assertIn('twitter:card content=summary_large_image', b); self.assertIn("viewport", b)
        st, b, h = self.get("/og.png"); self.assertEqual(h["Content-Type"], "image/png")
        self.assertEqual(json.loads(self.get("/healthz")[1])["ok"], True)
    def test_install(self):
        st, b, _ = self.get("/install?store=https://www.Ridge.com"); self.assertEqual(st, 200)
        self.assertIn("SHELFREADY_STORE=ridge.com", b); self.assertIn("Official Ridge shopping tool", b); self.assertIn("utm_medium=ai_agent", b)
        st, b, _ = self.get("/install?store=<script>"); self.assertEqual(st, 200); self.assertNotIn("<script>", b)
    def test_audit_redirect_and_validation(self):
        st, _, h = self.get("/audit?store=https://www.Ridge.com/x"); self.assertEqual(st, 303); self.assertEqual(h["Location"], "/r/ridge.com")
        self.assertEqual(self.get("/audit?store=127.0.0.1")[0], 400); self.assertEqual(self.get("/api/audit?store=localhost")[0], 400)
    def test_report_cache_escape_and_ratelimit(self):
        with mock.patch("auditcore.audit", return_value=json.loads(json.dumps(FAKE))) as m:
            st, b, _ = self.get("/r/example-store.com"); self.assertEqual(st, 200)
            self.assertIn("70</b>", b); self.assertIn("Agent can shop", b); self.assertIn("20/35", b); self.assertIn("cf.verified_bot_category", b); self.assertIn("kylebauer@mail.grokbot.com", b)
            self.assertNotIn("<script>alert", b); self.assertIn("og:title content=\"example-store.com scored 70/100", b)
            j = json.loads(self.get("/api/audit?store=example-store.com")[1]); self.assertEqual(j["claude_score"], 70); self.assertTrue(j["report_url"].endswith("/r/example-store.com"))
            self.assertEqual(m.call_count, 1)  # cached
            hdr = {"X-Forwarded-For": "203.0.113.9"}
            codes = []
            for i in range(app.RATE_PER_HOUR + 1):
                codes.append(self.get(f"/api/audit?store=store{i}.com", hdr)[0])
            self.assertEqual(codes[:app.RATE_PER_HOUR], [200] * app.RATE_PER_HOUR); self.assertEqual(codes[-1], 429)
            self.assertEqual(self.get("/r/example-store.com", hdr)[0], 200)  # cached reports never rate-limited
@unittest.skipUnless(LIVE, "set SHELFREADY_LIVE=1 for network tests")
class Live(unittest.TestCase):
    def test_allbirds(self):
        r = auditcore.audit("allbirds.com"); self.assertGreaterEqual(r["score"], 50); self.assertLess(r["elapsed_s"], 20)
if __name__ == "__main__": unittest.main(verbosity=1)
