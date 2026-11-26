# SMS and WhatsApp reminders

For patients (often elderly parents) who don't open apps. People add their mobile number on **Account → 📱 Mobile number**, confirm it with a 6-digit code, and then:
- visit reminders arrive by SMS/WhatsApp **1 hour before**, automatically;
- any other reminder can tick **"Also send an SMS"**.

Without a provider (on your own computer) the code and messages are printed in the Terminal, so you can test.

## Option A: MSG91 (India, cheapest)

Indian law requires every business SMS to use a **DLT-registered template**.
1. Register your business on a DLT portal (e.g. Jio, Vodafone Idea or Airtel's DLT site): entity, a sender ID like `CLINRA`, and two templates:
   - OTP: `Your Clinora code is {#var#}. It works for 10 minutes. Don't share it.`
   - Reminder: `Clinora reminder: {#var#} at {#var#}.`
2. Sign up at **https://msg91.com**, add the DLT details, and create two **Flows** using those templates (`otp` variable for the OTP flow; `var1`, `var2` for the reminder).
3. `.env`:
   ```
   SMS_PROVIDER=msg91
   MSG91_AUTHKEY=...
   MSG91_TEMPLATE_ID=reminder flow id
   MSG91_OTP_TEMPLATE_ID=otp flow id
   ```

## Option B: Twilio (worldwide)

```
SMS_PROVIDER=twilio
TWILIO_SID=AC...
TWILIO_TOKEN=...
TWILIO_FROM=+1...   (a Twilio number, or a Messaging Service SID)
```
For India you still need DLT registration through Twilio.

## Option C: WhatsApp reminders

If you set up the WhatsApp assistant (`docs/whatsapp.md`), create a **message template** in WhatsApp Manager, category *Utility*, named e.g. `visit_reminder`, body:
`Reminder from Clinora: {{1}} at {{2}}.`
After Meta approves it, add `WHATSAPP_REMINDER_TEMPLATE=visit_reminder`. Reminders then go by WhatsApp (codes still go by SMS).

## Safety

- Numbers must be confirmed with a code, so nobody can send reminders to someone else's phone.
- At most 20 messages per person per day, 4 codes per hour.
- People can remove their number any time; their SMS reminders stop at once.
