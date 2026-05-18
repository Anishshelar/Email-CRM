# Compliance FAQ

## GDPR (General Data Protection Regulation)

### Data Processing Agreement
A Data Processing Agreement (DPA) is available on request for EU customers. Email legal@company.com.

### Right to Erasure (Article 17)
Customers may request deletion of all personal data. We fulfil erasure requests within **30 days** of receiving a written request. Requests must be submitted to privacy@company.com.

### Right to Data Portability (Article 20)
Customers may request a machine-readable export of all personal data we hold. This is a **statutory obligation** — we must respond within **30 days**. The export is provided in JSON or CSV format. Requests are submitted to privacy@company.com.

### GDPR Request Handling Process
1. Log the request with exact received date (30-day clock starts immediately).
2. Send written acknowledgement to the customer within 3 business days.
3. Privacy Officer reviews and coordinates with Engineering to generate the export.
4. Deliver the export or confirm erasure within 30 days.
5. If the request cannot be fulfilled within 30 days, notify the customer and explain the reason (one 30-day extension is permissible under GDPR).

### Data Residency for EU Customers
- EU data residency is available on Pro and Enterprise plans.
- EU-resident accounts are hosted in Frankfurt (AWS eu-central-1).
- Standard accounts default to US-East (AWS us-east-1).

### Data Retention
- Customer data is retained for the duration of the contract plus 90 days.
- After 90 days post-cancellation, all data is permanently deleted from production systems.
- Backups are purged within 180 days.

## HIPAA (Health Insurance Portability and Accountability Act)

### Business Associate Agreement (BAA)
A BAA is available on request for healthcare customers on Pro or Enterprise plans. Contact legal@company.com. BAA execution is required before processing any Protected Health Information (PHI).

### Security Controls
- Data encrypted at rest using AES-256.
- Data encrypted in transit using TLS 1.3.
- Servers hosted in US-East (AWS) with optional EU residency for non-US healthcare customers.
- Full HIPAA control documentation available in the security questionnaire (provided under NDA).

## SOC 2 Type II

### Report Availability
The SOC 2 Type II report is available under NDA to Enterprise customers. Request via legal@company.com.
- Last audit completed: Q3 2023
- Trust Service Criteria covered: Security, Availability, Confidentiality
- Next audit scheduled: Q3 2024

## Data Residency Summary
| Region | Plans | Notes |
|---|---|---|
| US-East (default) | All plans | AWS us-east-1 |
| EU (Frankfurt) | Pro, Enterprise | GDPR-compliant; add-on fee applies |
| APAC | Roadmap Q2 2024 | Not yet available |
