"""Credentials for the opt-in end-to-end suites (backend_test.py, backend_part2_test.py, rbac_test.py).

Nothing is hardcoded: the Founder login comes from FOUNDER_EMAIL / FOUNDER_PASSWORD (the account
on the deployment behind WAVYGO_E2E_URL). Other role accounts are not seeded by the app; point
E2E_<ROLE>_EMAIL at existing users there. They share E2E_PASSWORD (defaults to FOUNDER_PASSWORD).
"""
import os

import pytest

BASE_URL = os.environ.get("WAVYGO_E2E_URL", "").rstrip("/")
API = f"{BASE_URL}/api"

FOUNDER_EMAIL = os.environ.get("FOUNDER_EMAIL", "").strip()
FOUNDER_PASSWORD = os.environ.get("FOUNDER_PASSWORD", "")
ROLE_PASSWORD = os.environ.get("E2E_PASSWORD") or FOUNDER_PASSWORD


def _role(role: str) -> dict:
    return {"email": os.environ.get(f"E2E_{role.upper()}_EMAIL", f"{role.lower()}@wavygo.in"), "password": ROLE_PASSWORD}


FOUNDER = {"email": FOUNDER_EMAIL, "password": FOUNDER_PASSWORD}
ADMIN, MANAGER, EMPLOYEE, INTERN = (_role(r) for r in ("Admin", "Manager", "Employee", "Intern"))

# Apply with `pytestmark = E2E_SKIP` in each suite.
E2E_SKIP = [
    pytest.mark.skipif(not BASE_URL, reason="set WAVYGO_E2E_URL to run the end-to-end suite"),
    pytest.mark.skipif(not (FOUNDER_EMAIL and FOUNDER_PASSWORD),
                       reason="set FOUNDER_EMAIL and FOUNDER_PASSWORD (the Founder login on the WAVYGO_E2E_URL "
                              "deployment) to run the end-to-end suite"),
]
