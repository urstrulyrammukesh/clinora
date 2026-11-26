# Send emails from Clinora ("Forgot password" links)

Clinora sends the password reset email through any **SMTP** email service. Pick one option below, put its details in `.env`, and restart the server.

**On your own computer without email set up:** nothing is sent. The reset link is printed in the Terminal window where Clinora runs, so you can still test "Forgot password".

---

## Option A: Brevo (free, 300 emails a day, recommended)

1. Sign up at **https://www.brevo.com**.
2. Go to **Senders, Domains & Dedicated IPs → Senders** and add the email you send from (for example `noreply@your-domain.com`). Verify it.
   - Best: also verify your **domain** there, so emails don't land in spam.
3. Go to **SMTP & API → SMTP** and click **Generate a new SMTP key**.
4. Add to `.env`:
   ```
   SMTP_HOST=smtp-relay.brevo.com
   SMTP_PORT=587
   SMTP_USER=your-brevo-login@example.com
   SMTP_PASS=your-smtp-key
   MAIL_FROM=noreply@your-domain.com
   ```

## Option B: Gmail (quick for testing, about 500 a day)

1. Turn on **2-Step Verification** for the Google account.
2. Open **https://myaccount.google.com/apppasswords**, create an app password named `Clinora`, and copy the 16 letters.
3. Add to `.env`:
   ```
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=yourname@gmail.com
   SMTP_PASS=the-16-letter-app-password
   MAIL_FROM=yourname@gmail.com
   ```
   Use your real Gmail password nowhere here, only the app password.

## Option C: Resend, Zoho, Amazon SES and others

Any service that gives you an SMTP host, port, username and password works the same way. Port `465` (SSL) and `587` (STARTTLS) are both supported.

---

## Test it

1. Restart Clinora.
2. Go to **Account → Log in → Forgot password?**, type your email and tap **Send reset link**.
3. The Terminal window shows `[email] sent 'Reset your Clinora password' to …` or, if something is wrong, `[email] FAILED …` with the reason.
4. Open the email and tap **Choose a new password**.

## How it keeps accounts safe

- The reply is always "If an account exists for this email, a link is on its way", so nobody can use it to find out who has an account.
- Each link works **once**, for **30 minutes**. Asking again cancels the older link.
- Resetting logs the person out on every other phone and computer, and puts an alert in their 🔔 bell.
- Limits: 3 requests per email per hour and 8 per network per hour.
- Keep `SMTP_PASS` only in `.env`. Never commit `.env` to GitHub.
