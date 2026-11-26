# Putting Clinora online and on the Google Play Store

Everything technical is ready in this project. These are the steps only you can do (they need your accounts and payments). Do them in this order.

---

## Step 1: Buy a domain (≈ ₹500–1,500 a year)
Buy a name such as `clinora.in` or `getclinora.com` from GoDaddy, Hostinger, Namecheap or Google's partner registrars.
Check first that nobody else uses "Clinora" as a brand in your country (search the name and the trademark site: https://ipindiaonline.gov.in/eregister/).

## Step 2: Put the website online with Render (≈ $7 a month + disk ≈ $0.25)
1. Make an account at https://render.com and connect your GitHub.
2. Click **New → Blueprint** and choose the `clinora` repository. Render reads `render.yaml` and sets everything up (server, address, a 5 GB disk for the database, photos, health records and backups). The full launch guide is `docs/go-live.md`.
3. Fill in the secret boxes Render asks for:
   - `PUBLIC_URL`: `https://` + your domain, e.g. `https://clinora.in`
   - `SUPPORT_EMAIL`: an email people can write to (for example a new Gmail made for Clinora)
   - `ANTHROPIC_API_KEY`: **make a new key** (the old one was shared in a chat; delete it in the Anthropic Console)
   - Payment keys (Razorpay / Stripe / PayPal): start with their **test** keys, switch to live keys after a test payment works
4. In Render → your service → **Settings → Custom Domains**, add your domain and copy the DNS records it shows into your domain company's DNS page. Render gives free HTTPS automatically.
5. Open your domain. You should see Clinora with a 🔒 lock.

Your local `.env` file and database are **not** on GitHub, so the online site starts with an empty database. That's what you want for real users.

## Step 3: Get on Google Search (free)
1. Go to https://search.google.com/search-console → **Add property** → your domain → verify it (copy the TXT record into your DNS).
2. In **Sitemaps**, submit `sitemap.xml`.
3. Google usually starts showing the site within a few days to a few weeks. Ask clinics to link to you: it helps a lot.

## Step 4: Make the Android app (free)
The website is already an installable app (PWA). We turn it into a Play Store app with Google's "Trusted Web Activity", using the free tool PWABuilder:
1. Go to https://www.pwabuilder.com, type your domain, press **Start**.
2. Choose **Package for stores → Android → Generate**. Use:
   - Package ID: `com.clinora.app` (or your own, it can never be changed later)
   - App name: `Clinora`, launcher name: `Clinora`
   - Keep "Signing key: create new" and **download the zip**.
3. In the zip you get `app-release-bundle.aab` (to upload), the signing key file and its passwords. **Back up the key file and passwords safely** (Google Drive + USB). Losing them makes updating hard.

## Step 5: Google Play Console ($25 once)
1. Sign up at https://play.google.com/console and pay the one-time $25.
   - Choose **Organization** if you have a registered business (needs a free D-U-N-S number). Health apps are easier to approve as an organization. A personal account also works.
2. **Create app** → name "Clinora", free, app.
3. Fill the **App content** forms (copy answers from `listing.md` and `data-safety.md` in this folder):
   - Privacy policy URL: `https://YOUR-DOMAIN/privacy`
   - App access: give a test login (make a demo patient account on the live site)
   - Ads: No
   - Content rating questionnaire: Medical / health reference, no violence, users can interact (messages, reviews)
   - Target audience: 18+
   - **Health apps declaration**: tick the features Clinora has (doctor directory, appointments, telehealth video calls, health information)
   - Data safety: see `data-safety.md`
   - Account deletion URL: `https://YOUR-DOMAIN/delete-account`
4. **Store listing**: copy title, short and full description from `listing.md`. Upload:
   - App icon: `assets/icons/icon-512.png`
   - Feature graphic (1024×500): make it from the home page image, or ask me
   - At least 2 phone screenshots: open your live site on a phone and take screenshots of Home, Nearby map, Food Scan, Directory, Reviews
5. **Testing → Closed testing**: upload the `.aab`, add **at least 12 testers** (their Gmail addresses: friends, family, clinic staff) and keep it running **14 days**. New personal accounts must do this before going public.
6. After 14 days: **Production → Create release** → upload the same `.aab` → **Send for review**. Review usually takes 1–7 days.

## Step 6: Link the app to your website (so it opens full screen, without a browser bar)
1. In Play Console → **Setup → App signing**, copy the **SHA-256 certificate fingerprint** of the *App signing key*.
2. In Render → Environment, set `TWA_PACKAGE` = your package ID (e.g. `com.clinora.app`) and `TWA_SHA256` = that fingerprint. Save (Render restarts).
3. Check `https://YOUR-DOMAIN/.well-known/assetlinks.json` shows them.

## Costs summary
| Item | Cost |
|---|---|
| Google Play account | $25 once |
| Domain | ₹500–1,500 / year |
| Render hosting + disk | ≈ $7.25 / month |
| Claude AI | pay per use (≈ ₹1–3 per chat or food scan) |
| Payments | % per payment (Razorpay ≈ 2%, Stripe ≈ 3%, PayPal ≈ 4–5%) |
| Apple App Store (optional, later) | $99 / year |

Prices change. Check each website before paying.

## Before real launch, please also
- Ask a lawyer to read `legal/privacy.html` and `legal/terms.html` (they are good drafts, not legal advice).
- Make the GitHub repository **private** if you plan to sell the business later.
- Do a real ₹1 test payment with live keys and refund it.
- Try a video call between two different phones.
