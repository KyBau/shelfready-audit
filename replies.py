#!/usr/bin/env python3
"""Make ready-to-paste X reply lines from audits (does NOT post anything).
Usage: python3 replies.py --base https://shelfready-audit.onrender.com @allbirds:allbirds.com @ridge:ridge.com
       python3 replies.py --base URL --file stores.txt      (lines: "@handle domain" or "domain")
       --api  : call <base>/api/audit instead of auditing locally"""
import sys, json, argparse, urllib.request, urllib.parse
import auditcore
def store_name(d): return d.split(".")[0].replace("-", " ").title()
def line(handle, d, score, issue, base, claude=None):
    url = f"{base.rstrip('/')}/r/{d}"; who = (handle + " ") if handle else ""
    sc = f"{score}/100"
    s = f"{who}{store_name(d)} scored {sc} on agent-readiness: {issue}. Full report: {url}"
    if len(s) > 280: s = f"{who}{store_name(d)} scored {score}/100: {issue}. Full report: {url}"
    if len(s) > 280: s = f"{who}{store_name(d)}: {score}/100. {url}"
    return s
def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--base", required=True); ap.add_argument("--file"); ap.add_argument("--api", action="store_true"); ap.add_argument("items", nargs="*")
    a = ap.parse_args(argv); items = list(a.items)
    if a.file: items += [l.strip().replace(" ", ":", 1) if " " in l.strip() else l.strip() for l in open(a.file) if l.strip() and not l.startswith("#")]
    out = []
    for it in items:
        h, _, d = it.rpartition(":") if ":" in it else ("", "", it)
        try:
            d = auditcore.normalize(d)
            if a.api: r = json.load(urllib.request.urlopen(f"{a.base.rstrip('/')}/api/audit?store={urllib.parse.quote(d)}", timeout=40))
            else: r = auditcore.audit(d)
            s = line(h, d, r["score"], r["top_issue"], a.base, r.get("claude_score"))
        except Exception as e: s = f"# {it}: skipped ({e})"
        print(s); out.append(s)
    return out
if __name__ == "__main__": main()
