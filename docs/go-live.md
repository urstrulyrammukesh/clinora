# Put Clinora live on the internet

This takes about **1–2 hours** the first time. At the end Clinora runs 24×7 at your own address, for example `https://your-domain.in`, with HTTPS.

**What you need**
- This GitHub repo (done ✅).
- A debit/credit card for **Render** (hosting) and a **domain name**.
- About **₹1,000–1,500 a month** at the start (see Costs at the bottom).

---

## ⚠️ Step 0: decide about the sample clinic

The chat books visits at **"Clinora Medical Center"** with 4 sample doctors and a demo address (in `index.html`: `CLINIC` and `DOCS`; in `server.py`: `DOCTOR_FEES` and the AI's instructions). On a real site, real people could book and even pay for doctors who don't exist.

Before launch, choose one:
- **A. Real partner clinic:** replace the clinic name, address, phone, hours, doctors and fees with a real clinic that agreed to use Clinora.
- **B. Keep it as a demo:** keep the "demo" wording visible, and **don't** turn on real payments.

Everything else (doctor accounts, directory, map, Food Scan, reminders, messages, reviews) is real and works for anyone.

---

Before real patients, also take **`docs/legal-review.md`** to a lawyer or mentor (health data rules in India).

## Step 1: Buy a domain (10 min)

1. **First pick a name that's safe to use**: [docs/custom-domain.md](custom-domain.md) (another company already runs `clinora.in`, so check for clashes before you buy). Then check it at **https://www.cloudflare.com/products/registrar/** (cheapest renewals), **https://www.namecheap.com** or **https://www.hostinger.in**.
2. Buy it for 1 year. Skip extras like "hosting", "email" or "SSL": Render gives HTTPS free.

## Step 2: Create the server on Render (20 min)

1. Sign up at **https://render.com** with **"Continue with GitHub"**.
2. Click **New → Blueprint**, pick the `clinora` repo, click **Connect**. Render reads `render.yaml` and sets up a web service with a 5 GB disk.
3. Render asks for the values marked `sync: false`. Fill these now:

| Setting | What to type |
|---|---|
| `PUBLIC_URL` | `https://your-domain.in` (your domain, with https, no / at the end) |
| `SUPPORT_EMAIL` | an email you read, e.g. `support@your-domain.in` or your Gmail |
| `ADMIN_SETUP_CODE` | a long random secret you invent, e.g. `river-mango-7731-quiet`. Write it down. |
| `ANTHROPIC_API_KEY` | from https://console.anthropic.com (add a few dollars of credit) |
| `SMTP_*`, `MAIL_FROM` | from `docs/email-setup.md` (Brevo is free) |

   Leave payments, social login and backup keys **empty for now**. You can add them later in **Environment**.
4. Click **Apply**. The first build takes 3–5 minutes. When it says **Live**, open the `https://clinora-xxxx.onrender.com` address it shows. Clinora is on the internet. 🎉

## Step 3: Connect your domain (15 min + waiting)

1. In Render, open the service → **Settings → Custom Domains → Add**: add `your-domain.in` and `www.clinora.in`.
2. Render shows the DNS records to add. Go to where you bought the domain → **DNS settings** and add exactly those records (usually an **A** record for `your-domain.in` and a **CNAME** for `www` pointing to `clinora-xxxx.onrender.com`). Delete any old "parking" A records.
3. Wait 10 minutes to a few hours. Render then shows ✅ **Verified** and issues the HTTPS certificate by itself.

## Step 4: Check everything (5 min)

In Render, open the service → **Shell**, and run:

```
python server.py --check
```

It lists ✅ ready, ⚠️ recommended, ❌ must fix. Fix every ❌ (in **Environment**, then **Manual Deploy → Restart**), and run it again until it says **Ready to go live**.

## Step 5: Create your admin account (2 min)

1. Open `https://your-domain.in/#dashboard`.
2. Fill in your name, email, a strong password and the **setup code** from Step 2.
3. You're the clinic admin. Add doctor logins from the dashboard.

Without the code nobody can create this account, so a stranger can't take over your dashboard.

## Step 6: Turn on the extras (when ready)

| Feature | Guide | Notes |
|---|---|---|
| Cloud copy of backups | `docs/backups.md` | **Do this in week 1.** Free on Cloudflare R2. |
| Uptime alerts | `docs/uptime.md` | Free. Emails you within 5 minutes if the site goes down. |
| Login with Google / Facebook / X | `docs/social-login.md` | Needs the real https address. |
| Payments | the comments at the top of `server.py` | Start with **test keys**, try a payment, then switch to **live** keys. |

**Payment webhooks** (each provider asks for a URL):
- Stripe: `https://your-domain.in/api/pay/webhook`
- Razorpay: `https://your-domain.in/api/pay/razorpay-webhook`
- PayPal: `https://your-domain.in/api/pay/paypal-webhook`

Put each provider's webhook secret in Environment (`STRIPE_WEBHOOK_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `PAYPAL_WEBHOOK_ID`). The check in Step 4 warns if one is missing or if you're still on test keys.

## Step 7: Test like a patient (15 min)

On your phone, not logged in as admin:
- [ ] Home page opens with 🔒 HTTPS; light/dark button works.
- [ ] Sign up as a patient → 🔔 shows "Welcome".
- [ ] Log out → **Forgot password?** → the email arrives → the link works.
- [ ] Sign up as a doctor on a second account → create a profile → it shows in World Directory and Nearby.
- [ ] Doctor sends verification → you approve it in the dashboard → ✓ Verified badge shows.
- [ ] Patient messages the doctor, reviews them, reports a test review → it appears in **⚑ Reports**.
- [ ] Add a reminder for 2 minutes from now → pop-up and bell arrive.
- [ ] Ask AI a question (needs AI credit).
- [ ] Dashboard → **💾 Back up now** works.
- [ ] `/privacy`, `/terms` and `/delete-account` show your support email.

## Step 8: Tell the world

- Add the site in **Google Search Console** (https://search.google.com/search-console) and submit `https://your-domain.in/sitemap.xml`.
- Put the link on your **LinkedIn**, **GitHub profile** and **portfolio**.
- Post your launch post (`clinora-launch-kit.md` in your Desktop/github-work folder).

---

## Costs (approx.)

| Item | Price |
|---|---|
| Render Starter web service (always on) | about $7 / month |
| Render 5 GB disk | about $1.25 / month |
| Domain (.in / .com) | ₹600–1,200 / year |
| Anthropic AI | pay per use; ₹400–800 a month is plenty at the start |
| Email (Brevo), backups (R2), maps | free at the start |

## Keep it healthy

- **One server only.** Clinora uses one database file, so keep the Render service at **1 instance** (don't turn on autoscaling).
- Every `git push` to `main` redeploys automatically. The disk keeps your data between deploys.
- Watch **Logs** in Render for `[backup] FAILED`, `[email] FAILED` or `[reminders]` errors.
- Once a month: download one backup from the dashboard and test it on your Mac (`docs/backups.md`).
- Never put keys or `.env` on GitHub. They go only in Render's **Environment**.
