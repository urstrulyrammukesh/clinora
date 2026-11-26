# Turn on "Log in with Google, Facebook and X"

Clinora already has the buttons and all the sign-in code. Each button switches on as soon as you add its keys to the `.env` file and restart the server. Until then it shows "coming soon", and email login always works.

**Before you start:** these companies only allow sign-in on a real web address with **https**, not on `localhost`. Do this once Clinora is live, for example at `https://clinora.in`, and set `PUBLIC_URL=https://clinora.in` in `.env`.

In every step below, replace `https://YOUR-DOMAIN` with your real address.

---

## 1. Google (about 10 minutes)

1. Go to **https://console.cloud.google.com** and sign in.
2. At the top, **Select a project → New project**. Name it `Clinora` and click **Create**.
3. In the menu, open **APIs & Services → OAuth consent screen**.
   - User type: **External** → **Create**.
   - App name: `Clinora`. Support email: your email.
   - App domain: `https://YOUR-DOMAIN`, Privacy policy: `https://YOUR-DOMAIN/privacy`, Terms: `https://YOUR-DOMAIN/terms`.
   - Save, then on the next screens keep the default scopes (`email`, `profile`, `openid`) and save.
   - Click **Publish app** so anyone can log in, not only test users.
4. Open **APIs & Services → Credentials → Create credentials → OAuth client ID**.
   - Application type: **Web application**.
   - **Authorized JavaScript origins:** `https://YOUR-DOMAIN`
   - Click **Create**.
5. Copy the **Client ID**. It looks like `123-abc.apps.googleusercontent.com`.
6. Add it to `.env`:
   ```
   GOOGLE_CLIENT_ID=123-abc.apps.googleusercontent.com
   ```

Google only needs the Client ID. Never put the Client *secret* in `.env` for this.

---

## 2. Facebook (about 15 minutes)

1. Go to **https://developers.facebook.com** → **My Apps → Create app**.
2. Use case: **Authenticate and request data from users with Facebook Login** → Next.
3. App name: `Clinora`, your contact email → **Create app**.
4. In the app dashboard, open **Use cases → Authentication and account creation → Customize**:
   - Make sure the **email** permission is added.
   - Under **Settings**, set **Valid OAuth Redirect URIs** to:
     `https://YOUR-DOMAIN/api/m/oauth/facebook/callback`
5. Open **App settings → Basic**:
   - Privacy policy URL: `https://YOUR-DOMAIN/privacy`
   - Terms of service URL: `https://YOUR-DOMAIN/terms`
   - User data deletion: **Data deletion instructions URL** → `https://YOUR-DOMAIN/delete-account`
   - Copy the **App ID** and click **Show** to copy the **App secret**.
6. Switch the app from **Development** to **Live** at the top of the dashboard.
7. Add to `.env`:
   ```
   FACEBOOK_APP_ID=your-app-id
   FACEBOOK_APP_SECRET=your-app-secret
   ```

---

## 3. X / Twitter (about 15 minutes)

1. Go to **https://developer.x.com** and sign up for the free developer account.
2. In the **Developer Portal**, open your **Project → App → Settings → User authentication settings → Set up**.
   - App permissions: **Read**. Turn on **Request email from users**.
   - Type of App: **Web App**.
   - **Callback URI:** `https://YOUR-DOMAIN/api/m/oauth/x/callback`
   - **Website URL:** `https://YOUR-DOMAIN`
   - Terms of service: `https://YOUR-DOMAIN/terms`, Privacy policy: `https://YOUR-DOMAIN/privacy`
   - Save.
3. Copy the **OAuth 2.0 Client ID** and **Client Secret** shown after saving (keys and tokens tab).
4. Add to `.env`:
   ```
   X_CLIENT_ID=your-client-id
   X_CLIENT_SECRET=your-client-secret
   ```

---

## 4. Restart and test

1. Restart Clinora (stop the server, then run `start.command` again).
2. Open **Account**. The Google button now shows Google's own button, and Facebook and X no longer say "coming soon".
3. Try each one. After signing in you land back on your Clinora account page.

## How accounts are matched

- The first time someone signs in with Google, Facebook or X, Clinora creates a **patient** account (or a **doctor** account if they chose "I'm a doctor" first).
- If an account with the same confirmed email already exists, they are logged into that account. No duplicate is made.
- People who sign up this way have no password. They can set one any time under **Account → Set a password**, and they delete their account by typing `DELETE`.
- Keep all keys only in `.env`. Never commit `.env` to GitHub.
