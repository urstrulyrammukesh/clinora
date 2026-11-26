# Clinora on WhatsApp

Patients message Clinora's WhatsApp number. The assistant answers in their language (Hindi, Hinglish, English…), finds real Clinora doctors and sends a **one-tap booking link**. Emergencies get the 112 message at once.

- With the Anthropic key: a friendly AI assistant that remembers the last few messages (kept 7 days).
- Without it: a simple menu. Patients send `doctor dentist Srinagar` and get a list.

## Setup (about 30 minutes, needs the live https site)

1. Go to **https://developers.facebook.com → My Apps → Create app → Business**, then add the **WhatsApp** product.
2. In **WhatsApp → API Setup** you get a test number. Later add your own business number (a phone number not used on normal WhatsApp).
3. Create a **permanent access token**: Business Settings → System users → add a system user → Generate token with `whatsapp_business_messaging` and `whatsapp_business_management`.
4. Copy into `.env` / Render:
   ```
   WHATSAPP_TOKEN=the-permanent-token
   WHATSAPP_PHONE_ID=the "Phone number ID" from API Setup
   WHATSAPP_VERIFY_TOKEN=any-long-random-words-you-choose
   WHATSAPP_APP_SECRET=App settings → Basic → App secret
   ```
   Restart Clinora.
5. **WhatsApp → Configuration → Webhook → Edit**:
   - Callback URL: `https://YOUR-DOMAIN/api/whatsapp/webhook`
   - Verify token: the same `WHATSAPP_VERIFY_TOKEN`
   - Then **Manage → subscribe to `messages`**.
6. Send "hi" to the number from your phone. You should get the Clinora reply.

## Good to know

- Meta allows free-form replies within **24 hours** of the patient's last message, which is how this assistant works. Clinora does not send marketing messages.
- Every message from Meta is checked with your app secret (`X-Hub-Signature-256`); anything else is refused.
- Put the number on your website, doctor pages and posters: `https://wa.me/91XXXXXXXXXX?text=hi`.
