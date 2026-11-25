# Google Play "Data safety" answers for Clinora

Answer the form like this. It matches what the code actually does (see `legal/privacy.html`).

**Does your app collect or share any of the required user data types?** Yes
**Is all of the user data collected by your app encrypted in transit?** Yes (HTTPS only)
**Do you provide a way for users to request that their data is deleted?** Yes: in the app (Account → Delete my account) and at `https://YOUR-DOMAIN/delete-account`

| Data type | Collected | Shared* | Optional? | Purpose |
|---|---|---|---|---|
| Personal info → Name | Yes | No | Required for accounts and bookings | App functionality, Account management |
| Personal info → Email address | Yes | No | Required for accounts | Account management |
| Personal info → Phone number | Yes | No | Required for bookings and doctor profiles | App functionality |
| Personal info → Address (doctors' clinic address) | Yes | No | Optional (doctors only) | App functionality |
| Location → Approximate and Precise location | Yes | Yes (OpenStreetMap search services, for map search only) | Optional | App functionality (nearby doctors, map) |
| Health and fitness → Health info | Yes | Yes (AI provider, to answer the user) | Optional | App functionality |
| Messages → Other in-app messages | Yes | No | Optional | App functionality |
| Photos and videos → Photos | Yes | Yes (AI provider, Food Scan only, not stored) | Optional | App functionality |
| Financial info → Purchase history | Yes | Yes (payment processor) | Optional | App functionality |
| App activity → Other user-generated content (reviews) | Yes | No | Optional | App functionality |

\* Google does not count data sent to a "service provider" that processes it only on your behalf as "sharing". The AI provider (Anthropic), the payment companies and the map services act as service providers here, so you may answer "No" to sharing for them. If unsure, answering "Yes" is the safer choice.

**Not collected:** contacts, call logs, SMS, files, calendar, web browsing history, device or advertising IDs, audio recordings (video calls go directly between the two devices and are not recorded).

**Payment card and UPI details:** not collected by Clinora. They are entered only on Razorpay / Stripe / PayPal pages.
