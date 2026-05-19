import httpx

r = httpx.get("http://localhost:8000/api/status/msg_038").json()
assert r["status"] == "Escalated", f'Expected Escalated, got {r["status"]}'
detail = httpx.get(f'http://localhost:8000/api/emails/{r["email_id"]}').json()
flags = detail["rule_flags"]
assert flags["skip_llm_pipeline"] == True, "msg_038 should have skip_llm_pipeline=True"
assert flags["security_flag"] == True, "msg_038 should have security_flag=True"
print("OK msg_038: ESCALATED, skip_llm_pipeline=True, security_flag=True")

r52 = httpx.get("http://localhost:8000/api/status/msg_052").json()
detail52 = httpx.get(f'http://localhost:8000/api/emails/{r52["email_id"]}').json()
flags52 = detail52["rule_flags"]
assert flags52["legal_flag"] == True, "msg_052 should have legal_flag=True"
assert flags52["gdpr_flag"] == True, "msg_052 should have gdpr_flag=True"
print("OK msg_052: legal_flag=True, gdpr_flag=True")

dup = httpx.post("http://localhost:8000/api/ingest", json={
    "message_id": "msg_038",
    "sender": "hacker@anon-collective.net",
    "subject": "test",
    "body": "test",
    "timestamp": "2023-10-01T00:00:00Z",
    "thread_id": "thread_test"
}).json()
assert dup["already_exists"] == True, "Duplicate should return already_exists=True"
print("OK duplicate: already_exists=True for msg_038")

print("All pre-flight checks passed.")
