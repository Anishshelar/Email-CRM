# Escalation Matrix

## Escalation Paths by Scenario

### Legal Threats and Cease-and-Desist Letters
- **First responder:** Legal team (legal@company.com)
- **Escalation path:** CEO + external legal counsel
- **SLA:** Immediate — do not respond to the customer until Legal has reviewed
- **Auto-reply:** Suppressed — any response must be drafted by Legal

### Security Incidents and Ransomware Threats
- **First responder:** Security team (security@company.com, PagerDuty 24/7)
- **Escalation path:** CTO → CEO
- **SLA:** Immediate — page the on-call security engineer within 15 minutes
- **Auto-reply:** Suppressed — no automated response to any threat actor

### GDPR Data Subject Requests (Right to Portability / Erasure)
- **First responder:** Privacy Officer (privacy@company.com)
- **Escalation path:** Legal team
- **SLA:** 30 days (statutory obligation under GDPR Article 20 / Article 17)
- **Action:** Log the request with received date; issue written acknowledgement within 3 business days

### Refund Requests and Billing Disputes
- **First responder:** Support agent
- **Escalation threshold:** Account value > $500/month → Customer Success Manager within 1 hour
- **SLA:** Acknowledge within 1 hour; resolve within 2 business days
- **Playbook:** See refund_policy.md — Churn Retention Playbook

### VIP Churn Threats (Cancellation Requests from High-Value Accounts)
- **First responder:** Customer Success Manager
- **Escalation path:** VP Sales
- **SLA:** 1 hour response; VP Sales engaged within 2 hours if no resolution
- **Trigger:** Any cancellation request from account > $500/month, or any customer on the VIP list

### P0 Production Incidents (Customer-Reported Outages)
- **First responder:** On-call engineer (PagerDuty)
- **Escalation path:** CTO
- **SLA:** 15-minute first response; 2-hour resolution target
- **Customer comms:** Status page updated within 15 minutes; direct email to affected accounts within 30 minutes

### PR Crisis and Media Inquiries
- **First responder:** Marketing/PR team (pr@company.com)
- **Escalation path:** CEO
- **SLA:** Same business day
- **Public review threats (G2, Trustpilot, Twitter/X):** Escalate to Customer Success Manager immediately; do not dismiss or argue publicly

### SLA Breach with Legal Escalation
- **First responder:** Customer Success Manager
- **Escalation path:** Legal team + CTO
- **SLA:** Immediate upon identification
- **Action:** Issue SLA credit proactively; do not wait for customer to request

## Contact Directory
| Team | Contact | Availability |
|---|---|---|
| Security | security@company.com | PagerDuty 24/7 |
| Legal | legal@company.com | Business hours; urgent via on-call |
| Privacy / GDPR | privacy@company.com | Business hours |
| Customer Success | success@company.com | Business hours |
| Media / PR | pr@company.com | Business hours |
| Billing | billing@company.com | Business hours |
