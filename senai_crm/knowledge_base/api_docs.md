# API Documentation

## Rate Limits by Plan

| Plan | Requests per Minute | Burst Limit | Daily Cap |
|---|---|---|---|
| Starter | 100 req/min | 200 req/min for 30s | 50,000/day |
| Standard | 500 req/min | 1,000 req/min for 30s | 250,000/day |
| Pro | 1,000 req/min | 2,000 req/min for 30s | 1,000,000/day |
| Enterprise | Custom (up to 10,000 req/min) | Negotiated | Unlimited |

Rate limit headers are returned on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.
Exceeding the rate limit returns HTTP 429 with a `Retry-After` header.

## API v1 Deprecation
- **API v1 sunset date: December 31, 2023.**
- After this date, v1 endpoints return HTTP 410 Gone.
- All integrations must migrate to API v2. Migration guide: docs.company.com/v2-migration.

## API v2 Breaking Changes
The following changes are required when migrating from v1 to v2:

1. **Authentication header change**
   - v1: `X-API-Key: <your_key>`
   - v2: `Authorization: Bearer <your_key>`

2. **Paginated responses**
   All list endpoints now return: `{"data": [...], "next_cursor": "...", "has_more": true|false}`
   Pass `?cursor=<next_cursor>` to fetch the next page.

3. **Webhook signature validation (required)**
   All webhook payloads are signed with HMAC-SHA256.
   Validate the `X-Signature-256` header against `HMAC-SHA256(webhook_secret, raw_body)`.
   Unvalidated webhooks should be rejected by your server.

4. **New required header: `X-Workspace-ID`**
   All v2 requests must include `X-Workspace-ID: <your_workspace_id>`.
   Your workspace ID is available in Settings → API.

## v2 Migration Steps
1. Generate a v2 API key in Settings → API → Generate v2 Key.
2. Replace `X-API-Key: <key>` with `Authorization: Bearer <key>` in all requests.
3. Add `X-Workspace-ID: <id>` to all requests.
4. Update list endpoint consumers to handle `{data, next_cursor, has_more}` envelopes.
5. Implement HMAC-SHA256 webhook signature validation.
6. Test against the v2 sandbox (sandbox.api.company.com) before switching production traffic.

## Webhooks
Webhook events are delivered via HTTP POST to your configured endpoint. Supported events:
- `email.classified` — fired after LLM classification completes
- `thread.escalated` — fired when a thread status changes to Escalated
- `contact.churn_risk_high` — fired when churn_risk_score exceeds 0.8
- `sla.breach_warning` — fired when uptime approaches the SLA threshold

Webhook delivery: at-least-once. Idempotency keys are provided in the `X-Event-ID` header.

## Error Codes
| HTTP Status | Meaning |
|---|---|
| 400 Bad Request | Malformed request body |
| 401 Unauthorized | Invalid or missing API key |
| 403 Forbidden | Valid key but insufficient permissions |
| 422 Unprocessable Entity | Validation error (see `detail` field) |
| 429 Too Many Requests | Rate limit exceeded (see `Retry-After`) |
| 500 Internal Server Error | Platform error — check status.company.com |
