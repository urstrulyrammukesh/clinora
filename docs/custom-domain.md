# Your own domain: choose a safe name, connect it, protect it

Today Clinora lives at `clinora-cwxu.onrender.com`. A short address of your own looks professional, is easier to share on WhatsApp, and lets you put Cloudflare's free protection in front of the site.

**Cost:** about ₹700–1,200 a year for `.in` / `.com`. Everything else here is free.

## 1. Choose a name that won't get you into trouble (do this first)

Another health company already runs **clinora.in**. Using a name that is the same as, or confusingly close to, someone else's brand in the **same field** (health) can lead to a legal notice, a forced rename, or losing the domain. Adding a letter ("Clinoraa") or changing the ending (`.app`, `.health`) does **not** make it safe: the test is whether patients could confuse the two.

Before you buy anything:

1. **Search the trademark register:** https://tmrsearch.ipindia.gov.in/tmrpublicsearch/ (India; class 44 is medical services, class 9 and 42 cover apps and software). Also search the name on Google, the Play Store and the App Store.
2. **Shortlist 3–5 names** that are short, easy to spell over the phone, and not used by a health company. Ideas for the style: a made-up word (like "Practo", "Zocdoc"), or two simple words (`carebridge`, `sehatsetu`, `nabzcare`). Check each one at step 3.
3. **Check the domain is free** at https://www.cloudflare.com/products/registrar/ (sells at cost, no renewal price jump) or https://www.namecheap.com.
4. If you're unsure, ask a trademark lawyer for a 30-minute "clearance search" (often ₹2,000–5,000). It's much cheaper than a rename later.
5. When you've decided, **file your own trademark** (from ₹4,500 for a startup/individual, class 44) so nobody can take the name from you.

> Changing the name in the code is easy (it's mostly text). Ask and it can be done in one go: the page title, app name, manifest, emails, PDFs and README.

## 2. Buy it (10 minutes)

- Buy **1 year** to start. Skip "hosting", "email", "SSL" and "privacy" add-ons: Render gives HTTPS free, and Cloudflare includes privacy.
- Turn on **auto-renew** and **two-factor login** on the registrar account (losing a domain to expiry or a hacked account is a common way sites die).

## 3. Connect it to Render (15 minutes + waiting)

1. Render → your **clinora** service → **Settings → Custom Domains → Add**: add `your-domain.in` and `www.your-domain.in`.
2. Render shows DNS records. At your registrar (or Cloudflare) → **DNS**, add exactly those (usually an `A` record for the bare domain and a `CNAME` for `www` → `clinora-cwxu.onrender.com`). Delete old "parking" records.
3. Wait until Render shows **Verified** and **Certificate issued** (minutes to a few hours).
4. Render → **Environment** → set `PUBLIC_URL` = `https://your-domain.in` (no `/` at the end) → **Save** → **Manual Deploy**.
5. Check: `python server.py --check` locally with the same settings, or open `https://your-domain.in/api/status`.

Things that use `PUBLIC_URL` and update by themselves: links in emails, WhatsApp messages and receipts, the sitemap for Google, link previews, the Play Store app link.

## 4. Free protection with Cloudflare (optional, recommended)

If the domain's DNS is on Cloudflare (free plan):

| Setting | Where | Value |
|---|---|---|
| Proxy | DNS → the records → orange cloud | **On** (hides the server, blocks floods) |
| SSL/TLS mode | SSL/TLS → Overview | **Full (strict)** |
| Always use HTTPS | SSL/TLS → Edge Certificates | On |
| Bot Fight Mode | Security → Bots | On |
| Rate limiting rule | Security → WAF → Rate limiting | `/api/m/login`, `/api/auth/login`: 20 requests / minute per IP → Block |

Cloudflare also adds the visitor's country to every request (`CF-IPCountry`), which makes Clinora's visitor statistics more accurate on its own.

## 5. After the switch

- Google Search Console: add the new domain and submit `https://your-domain.in/sitemap.xml`.
- Update links on GitHub (repo **About → Website**), LinkedIn, your portfolio and the Play Store listing.
- Keep `clinora-cwxu.onrender.com` working: Render keeps it, so old links still open.
