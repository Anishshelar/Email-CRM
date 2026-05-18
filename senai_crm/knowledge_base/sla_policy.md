# SLA Policy

## Uptime Guarantee
- **Guaranteed uptime: 99.9%** measured on a monthly rolling basis.
- Uptime is calculated as: (total minutes − downtime minutes) / total minutes × 100.
- Scheduled maintenance windows are excluded from downtime calculations. Customers are notified at least **48 hours** in advance.
- Historical uptime is published on status.company.com.

## Incident Severity Levels

| Severity | Definition | First Response SLA | Resolution Target |
|---|---|---|---|
| P0 — Production Down | All customers unable to access the platform | **15 minutes** | 2 hours |
| P1 — Major Feature Impaired | Core feature degraded for >10% of customers | **1 hour** | 8 hours |
| P2 — Minor Issue | Non-critical feature degraded or workaround available | **4 hours** | 48 hours |
| P3 — Cosmetic / Enhancement | UI issue, documentation request | 1 business day | Next release |

## SLA Credit Formula
If uptime falls below 99.9% in a given month, affected customers receive automatic service credits:
- **10% of the monthly fee** for each hour of excess downtime beyond the SLA threshold.
- Credits are **capped at 30% of the monthly fee** per incident.
- Credits are applied automatically to the next invoice.
- Customers must report potential SLA breaches within **30 days** of the incident to be eligible.

### Credit Calculation Example
Monthly fee: $299 (Pro plan). Monthly SLA threshold: 99.9% = 43.8 minutes allowed downtime.
Actual downtime: 3 hours 43 minutes (excess: 3 hours).
Credit: 3 × 10% × $299 = **$89.70** (29.9% of monthly fee, within the 30% cap).

## Root Cause Analysis (RCA)
- **P0 incidents:** Written RCA delivered within **24 hours** of resolution.
- **P1 incidents:** Written RCA delivered within **72 hours** of resolution.
- RCAs include: timeline of events, root cause, impact assessment, and steps taken to prevent recurrence.
- RCAs are emailed to the primary account contact and posted to status.company.com.

## Exclusions from SLA
The SLA does not cover:
- Downtime caused by customer-side infrastructure or third-party integrations.
- Force majeure events (natural disasters, widespread internet outages).
- Scheduled maintenance (with 48-hour advance notice).
- Incidents caused by customer misuse of the API beyond documented rate limits.

## Reporting an Incident
1. Check status.company.com for any known active incidents.
2. If not listed, open a support ticket at support.company.com or email support@company.com.
3. For P0 emergencies: call the emergency line at +1-800-XXX-XXXX (Enterprise customers only).
