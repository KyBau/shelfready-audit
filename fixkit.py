#!/usr/bin/env python3
"""ShelfReady fix-kit generator: audit row (results.csv from agent_readiness) + observed edge info -> merchant-ready fix kit (markdown)."""
import csv, sys, os, json
LLMS = """# {name}
> {name} sells {what}. AI agents may browse our public catalog and hand shoppers a cart link; checkout happens on {domain}.

## Shop
- Catalog (JSON): https://{domain}/products.json
- Product JSON: https://{domain}/products/{{handle}}.js
- Cart link format: https://{domain}/cart/{{variant_id}}:{{qty}},{{variant_id}}:{{qty}}
- Agent connector (MCP): {mcp}

## Policies
- Returns: https://{domain}/policies/refund-policy
- Shipping: https://{domain}/policies/shipping-policy

## Rules for agents
- Never place orders or enter payment details; give the shopper the cart link.
- Quote prices and availability from the product JSON, not from cached text.
"""
LIQUID = """{%- comment -%} ShelfReady: schema.org Product JSON-LD. Put this in sections/main-product.liquid (or snippets/shelfready-jsonld.liquid and render it there). {%- endcomment -%}
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ProductGroup",
  "name": {{ product.title | json }},
  "description": {{ product.description | strip_html | truncate: 500 | json }},
  "url": {{ shop.url | append: product.url | json }},
  "brand": {"@type": "Brand", "name": {{ product.vendor | json }}},
  "productGroupID": {{ product.id | json }},
  "image": {{ product.featured_image | image_url: width: 1200 | prepend: 'https:' | json }},
  "hasVariant": [
    {%- for v in product.variants -%}
    {
      "@type": "Product",
      "sku": {{ v.sku | json }},
      "name": {{ v.title | json }},
      {%- if v.barcode != blank -%}"gtin": {{ v.barcode | json }},{%- endif -%}
      "offers": {
        "@type": "Offer",
        "url": {{ shop.url | append: v.url | json }},
        "price": {{ v.price | divided_by: 100.0 | json }},
        "priceCurrency": {{ cart.currency.iso_code | json }},
        "availability": "https://schema.org/{% if v.available %}InStock{% else %}OutOfStock{% endif %}"
      }
    }{% unless forloop.last %},{% endunless %}
    {%- endfor -%}
  ]
}
</script>"""
NEXT = """// Headless (Next.js / Hydrogen) equivalent. Render this in the product page component.
export function ProductJsonLd({ product, origin }) {
  const data = {
    "@context": "https://schema.org", "@type": "ProductGroup", name: product.title,
    description: product.description?.slice(0, 500), url: `${origin}/products/${product.handle}`,
    brand: { "@type": "Brand", name: product.vendor }, productGroupID: String(product.id),
    hasVariant: product.variants.map(v => ({ "@type": "Product", sku: v.sku, name: v.title,
      offers: { "@type": "Offer", price: Number(v.price.amount ?? v.price), priceCurrency: v.price.currencyCode ?? "USD",
        availability: `https://schema.org/${v.availableForSale ?? v.available ? "InStock" : "OutOfStock"}` } })),
  };
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />;
}"""
CF = """Cloudflare -> Security -> WAF -> Custom rules -> Create rule (put it ABOVE any bot-blocking rule)
Name: ShelfReady - allow verified AI agents
Expression:
  (cf.client.bot) or (cf.verified_bot_category in {"AI Assistant" "AI Search" "AI Crawler"})
Action: Skip -> All remaining custom rules, Rate limiting rules, Managed rules, Super Bot Fight Mode
Also: Security -> Bots -> AI Crawl Control (or "Block AI bots"): set Claude-User / ChatGPT-User / Perplexity-User (user-triggered fetches) to Allow.
Note: the verified-bot check depends on Cloudflare's IP verification, so spoofed user agents stay blocked. Check the field and category names in your dashboard before saving."""
VERCEL = """Vercel -> Project -> Firewall:
1. Check for a custom rule or rate limit matching /products.json, or a 'Bot Protection' / 'Attack Challenge Mode' setting. A plain curl got HTTP 429 on /products.json.
2. Add a custom rule above it: IF path starts with /products OR /policies OR /cart, AND user-agent matches (ClaudeBot|Claude-User|Claude-SearchBot|GPTBot|ChatGPT-User|OAI-SearchBot|PerplexityBot), THEN Bypass (or raise the rate limit to ~60 req/min per IP).
3. Headless storefronts don't serve Shopify's /products.json by default. Proxy it to the Shopify origin, or expose an equivalent catalog route, so agents get a machine-readable catalog."""
CLOUDFRONT = """AWS WAF on CloudFront: the edge returned 200 to a Claude-User UA, so no edge change is needed. If you add AWS WAF Bot Control later, put AI agents in a label-based allow rule (awswaf:managed:aws:bot-control:bot:category:ai / verified) ABOVE the block rules."""
def kit(row, edge, what):
    d = row["domain"]; name = d.split(".")[0].capitalize(); fixes = []
    if row.get("claude_fetch_status") == "403" or "Cloudflare" in edge and row.get("claude_fetch_readable") == "False":
        fixes.append(("P0 - Let Claude reach your product pages", f"Observed: product pages return HTTP 403 to a Claude-User user agent and 200 to a normal browser. Edge: {edge}.", CF))
    if (row.get("products_json") or "").startswith(("429", "404", "ERR")):
        fixes.append(("P0 - Make your catalog machine-readable", f"Observed: /products.json returned {row['products_json'].split('/')[0]}. Edge: {edge}.", VERCEL if "Vercel" in edge else CF))
    if row.get("jsonld_product") == "False":
        fixes.append(("P1 - Add schema.org Product markup", ("Observed: no JSON-LD Product/ProductGroup on the product page, so agents have to guess price and stock." if row.get("product_page") not in ("n/a", "") else "Not verified: the audit couldn't reach a product page. Check that your product template emits this markup."),
                      (NEXT if edge.split()[0] in ("Vercel", "CloudFront") else LIQUID) + "\n\n--- Liquid version (Online Store 2.0 themes) ---\n" + LIQUID))
    if row.get("llms_txt") == "False":
        fixes.append(("P1 - Publish /llms.txt", "Observed: no llms.txt.", "Serve this at https://%s/llms.txt (Shopify: Online Store -> Navigation -> URL redirect to a page, or a headless route):\n\n" % d + LLMS.format(name=name, domain=d, what=what, mcp="https://<your-shelfready-host>/mcp")))
    if row.get("storefront_mcp_tools") in ("0", "1", ""):
        fixes.append(("P2 - Give agents real shopping tools (ShelfReady connector)", f"Observed: Shopify storefront MCP tools exposed = {row.get('storefront_mcp_tools') or 0} (policies FAQ only, if any).",
                      f"Run ShelfReady with SHELFREADY_STORE={d} SHELFREADY_ALLOW_ANY_STORE=0 to expose search_products, get_product, build_cart_link and get_policies. Then submit it to Claude's directory (community tier), Grok custom connectors and Muse."))
    out = [f"# ShelfReady fix kit: {d}", f"Audit run 2026-10-13 (agent_readiness). Overall score {row['score']}/100, Claude-readiness {row.get('claude_score')}/100. Edge: {edge}.", ""]
    for i, (t, why, how) in enumerate(fixes, 1): out += [f"## {i}. {t}", why, "", "```", how, "```", ""]
    out += ["## Verify after shipping", f"```\ncurl -s -o /dev/null -w '%{{http_code}}\\n' -A 'Mozilla/5.0 (compatible; Claude-User/1.0; +Claude-User@anthropic.com)' https://{d}/\ncurl -s 'https://{d}/products.json?limit=1' | head -c 200\npython3 agent_readiness/audit.py <(echo {d})\n```",
            "Note: a UA-only test can't prove Claude's real IPs pass. Check your Cloudflare/Vercel logs for verified ClaudeBot hits too."]
    return "\n".join(out)
if __name__ == "__main__":
    src = sys.argv[1]; edges = json.loads(sys.argv[2]); whats = json.loads(sys.argv[3]); os.makedirs("fixkits", exist_ok=True)
    for row in csv.DictReader(open(src)):
        if row["domain"] in edges:
            p = f"fixkits/{row['domain'].split('.')[0]}.md"; open(p, "w").write(kit(row, edges[row["domain"]], whats.get(row["domain"], "products"))); print("wrote", p)
