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
| Files and docs (health records: lab reports, scans) | Yes | No (encrypted; shared only with a doctor the user picks) | Optional | App functionality |
| Health and fitness → Health info (visit reasons, prescriptions, medicine reminders) | Yes | No | Optional | App functionality |
| Photos and videos → Photos (prescription photos, read by AI, not stored) | Yes | Yes (AI provider) | Optional | App functionality |
| Photos and videos → Videos (doctor demo videos, patient video reviews) | Yes | No | Optional | App functionality |
| Personal info → Other info (family members' names, relation, birth year) | Yes | No | Optional | App functionality |
| Device or other IDs (push notification token) | Yes | Yes (Google/Apple/Mozilla push service delivers alerts) | Optional | App functionality |

\* Google does not count data sent to a "service provider" that processes it only on your behalf as "sharing". The AI provider (Anthropic), the payment companies and the map services act as service providers here, so you may answer "No" to sharing for them. If unsure, answering "Yes" is the safer choice.

**Not collected:** contacts, call logs, SMS, files, calendar, web browsing history, device or advertising IDs, audio recordings (video calls go directly between the two devices and are not recorded).

**Payment card and UPI details:** not collected by Clinora. They are entered only on Razorpay / Stripe / PayPal pages.


## Health apps declaration (Play Console → App content → Health apps)
Clinora fits **"Medical: telemedicine/appointment booking, medication reminders, health records"**. Tick those, and state:
- Clinora does not diagnose or treat; doctors on the platform are responsible for their advice and prescriptions.
- Doctor registration numbers are checked against the official register before the ✓ Verified badge.
- Health records are encrypted and only shared with a doctor the user chooses, for one visit.
Link the privacy policy (`https://YOUR-DOMAIN/privacy`) and the account deletion page (`https://YOUR-DOMAIN/delete-account`).
