"""SPEC-AUTH-07 — the public site may call member-api with credentials."""

import sys

sys.path.insert(0, r"C:\Users\bryan\Desktop\Ongoing\ESC - Copy\member-api")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


settings = get_settings()
public = settings.public_frontend_url
print(f"public origin: {public}")
check("public site is in cors_origins", public in settings.cors_origins,
      str(settings.cors_origins))

client = TestClient(app)

# Preflight, exactly as a browser sends it before a credentialed GET.
res = client.options(
    "/me/learning",
    headers={
        "Origin": public,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "content-type",
    },
)
check("preflight allowed", res.status_code in (200, 204), str(res.status_code))
check("origin echoed back",
      res.headers.get("access-control-allow-origin") == public,
      res.headers.get("access-control-allow-origin", "missing"))
check("credentials allowed",
      res.headers.get("access-control-allow-credentials") == "true",
      res.headers.get("access-control-allow-credentials", "missing"))

res = client.get("/me/learning", headers={"Origin": public})
check("unauthenticated request is 401, not a CORS failure",
      res.status_code == 401, str(res.status_code))
check("401 still carries CORS headers",
      res.headers.get("access-control-allow-origin") == public,
      res.headers.get("access-control-allow-origin", "missing"))

# A random site must not be allowed to read the account.
res = client.options(
    "/me/learning",
    headers={
        "Origin": "https://evil.example",
        "Access-Control-Request-Method": "GET",
    },
)
check("unknown origin is not allowed",
      res.headers.get("access-control-allow-origin") != "https://evil.example",
      res.headers.get("access-control-allow-origin", "none"))

# The login entry point the public site uses.
res = client.get("/auth/google/login?next=public", follow_redirects=False)
check("login?next=public redirects to Google",
      res.status_code in (302, 307) and "accounts.google.com" in res.headers.get("location", ""),
      f"{res.status_code} {res.headers.get('location', '')[:60]}")

print(f"\n{checks - len(failures)}/{checks} checks passed")
if failures:
    print("FAILED:", ", ".join(failures))
    sys.exit(1)
print("SSO wiring verification PASSED")
