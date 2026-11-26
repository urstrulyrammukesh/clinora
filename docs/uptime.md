# Know at once if Clinora goes down (free, 5 minutes)

Clinora has a health address: **`https://YOUR-DOMAIN/api/status`**. It answers within a second when the site is running. A free monitor checks it every 5 minutes and emails (or messages) you if it stops.

## Set up UptimeRobot (free)

1. Sign up at **https://uptimerobot.com** (the free plan is enough).
2. Click **+ New monitor**:
   - Monitor type: **HTTP(s)**
   - Friendly name: `Clinora`
   - URL: `https://YOUR-DOMAIN/api/status`
   - Monitoring interval: **5 minutes**
3. Under **Alert contacts**, tick your email. Optional: add the free **Telegram** or mobile app alerts too.
4. Click **Create monitor**.
5. Optional: add a second monitor for the home page, `https://YOUR-DOMAIN/`.

## Make a public status page (optional)

In UptimeRobot open **Status pages → Create**, add the Clinora monitor and publish it, e.g. `status.YOUR-DOMAIN`. Link it from your support email signature so people can check if it's just them.

## Also turn on Render's own alerts

In Render open **Account settings → Notifications** and turn on email for **failed deploys** and **service down**.

## When you get an alert

1. Open the site yourself. Is it down for you too?
2. Render dashboard → **Logs**: look at the last lines (errors show as `Traceback`, `[backup] FAILED`, `[email] FAILED`...).
3. Render → **Events**: did a deploy just fail? Click **Rollback** to the last good deploy.
4. Still stuck? **Manual Deploy → Restart service**.
