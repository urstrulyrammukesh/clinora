# Legal & privacy review checklist (before real patients)

This is **not legal advice**. It is a list to take to a lawyer, a mentor at your college, or an incubator legal clinic, so their time is spent on the right questions. Clinora handles **health data**, so a short professional review before launch is worth it.

Bring: this file, `legal/privacy.html`, `legal/terms.html`, `legal/delete-account.html`, and a 10-minute demo of the site.

## 1. India's Digital Personal Data Protection Act, 2023 (DPDP Act)

- [ ] **Notice & consent:** is the sign-up notice clear enough on what we collect and why? Do we need a separate consent tick for health details (reasons for visits, prescriptions, reminders)?
- [ ] **Children:** the Act asks for verifiable parental consent for anyone under 18. Today the Terms say "adults; under 18 only with a guardian's consent". Is that enough, or do we need an age check?
- [ ] **Family members:** users add parents and children (name, relation, birth year) and book for them. What consent wording do we need?
- [ ] **Rights:** access, correction, deletion, grievance. We have in-app deletion and a support email. Do we need a named **Grievance Officer** and a response time?
- [ ] **Data breaches:** what must we do, and how fast (Data Protection Board and affected users)? Write a 1-page breach plan.
- [ ] **Processors:** we share data with Anthropic (AI), the email service, push services (Google/Apple/Mozilla), payment companies, hosting and backup storage. Do we need contracts (DPAs) with each?
- [ ] **Cross-border transfer:** the AI provider and push services are outside India. Is that allowed for our data, and what must the privacy policy say?
- [ ] **Retention:** backups are kept up to 30 days; booking and payment records "as long as the law requires". Is that acceptable? Which law sets the period?

## 2. Telemedicine Practice Guidelines (India, 2020)

- [ ] **Doctor verification:** we check council registration numbers by hand against the NMC/State register before the ✓ badge. Should unverified doctors be allowed to offer **video** visits at all?
- [ ] **Patient consent** for video consultations: is starting a video visit enough, or do we need explicit consent text?
- [ ] **Prescriptions:** Clinora does not issue prescriptions. Do the Terms make clear that doctors are responsible for their own advice and prescriptions?
- [ ] The **"Read a prescription"** feature only suggests reminders the patient checks. Is the warning text enough?

## 3. Platform rules (IT Act 2000 & IT Rules 2021)

- [ ] Clinora hosts user content (reviews, videos, messages). Do we count as an **intermediary**, and what does that require (grievance officer, complaint timelines, takedown process)? We have Report + admin actions already.
- [ ] **Reviews:** how do we handle a doctor who says a review is defamatory?

## 4. Medical & consumer

- [ ] Medical disclaimer wording on the site, the AI chat, Food Scan and doctor pages.
- [ ] **Fees & cancellations:** doctors set fees; patients pay the doctor directly. Do we need a refund/cancellation policy page?
- [ ] **Emergency:** we show local emergency numbers. Is the "not for emergencies" wording strong enough?

## 5. Business basics

- [ ] Register the business (sole proprietorship / LLP / private limited) before taking payments.
- [ ] Trademark search for the name "Clinora" in India.
- [ ] Who owns the code and content (you as founder): write it down if others join.

After the review, update `legal/*.html` and the "Last updated" date, then run `python server.py --check` before launch.
