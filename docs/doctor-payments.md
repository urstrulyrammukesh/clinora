# Online payment to doctors (Razorpay Route)

Patients pay the doctor's fee when they book. Razorpay splits the payment: the doctor's share goes **straight to the doctor's bank account**, and Clinora keeps `PLATFORM_FEE_PCT` (default **5%**). Clinora never holds the doctor's money.

On your own computer (no Razorpay keys) everything works in **demo mode**: a "Pay (demo)" button, no money moves.

## One-time setup (Clinora's Razorpay account)

1. Create a Razorpay account at **https://razorpay.com** and finish KYC for Clinora's business.
2. Ask Razorpay support to **enable Route** on your account (Dashboard → Route).
3. Put your keys in `.env` / Render: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, and optionally `PLATFORM_FEE_PCT=5`.
4. Razorpay → **Webhooks** → URL `https://YOUR-DOMAIN/api/pay/razorpay-webhook`, events **payment.captured** and **order.paid**, with the same secret.

## Adding a doctor

1. Check the doctor is **✓ Verified** (Clinic Dashboard → Doctor verification).
2. Razorpay → **Route → Linked accounts → Create**: the doctor's name, email, PAN and bank account. Razorpay checks it.
3. Copy the id (looks like `acc_XXXXXXXXXXXX`) into **Clinic Dashboard → 💸 Doctor payouts** next to that doctor and press **Save**.
4. The doctor can now tick **"Patients pay online when booking"** in their Online booking settings.

## How it works for patients

- After choosing a time they pay with UPI, card or net banking. The time is **held for 15 minutes**; if they don't pay, it is released automatically.
- The doctor is only notified, and reminders are only set, **after** the payment succeeds.
- **Refunds:** full refund if the doctor cancels, or if the patient cancels **24 hours or more** before. The refund also takes back the doctor's share (Route "reverse_all"). Later cancellations are not refunded (shown to patients before booking).
- Only **INR** fees can be paid online (Route works in India). Other currencies: patients pay the doctor directly.

Test first with Razorpay **test keys** (`rzp_test_…`) and test cards/UPI before switching to live keys.
