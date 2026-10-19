import os
import pytest
from fastapi.testclient import TestClient
from apis.main import app

# Use one of the whitelisted demo emails from your .env definition
DEMO_EMAIL = "compliance@company.com"
DEMO_PASSWORD = "password123"

def test_auth_login_demo_challenge():
    """
    Tests that hitting the /login route with DEMO_LOGIN_ENABLED active
    correctly returns a 200 OK along with the demo challenge and session.
    """
    # Verify env is set up for demo login
    if os.getenv("DEMO_LOGIN_ENABLED") != "true":
        pytest.skip("DEMO_LOGIN_ENABLED is not set to true, skipping demo auth test")

    login_payload = {
        "email": DEMO_EMAIL,
        "password": DEMO_PASSWORD
    }
    
    # We call the FastAPI routes directly through the TestClient inside a lifespan context manager
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json=login_payload)
        
        assert response.status_code == 200, f"Login failed: {response.text}"
        json_data = response.json()
        
        assert json_data.get("mfa_required") is True
        assert json_data.get("challenge") == "SOFTWARE_TOKEN_MFA"
        assert "session" in json_data
        assert json_data.get("session") == f"demo-session-{DEMO_EMAIL}"

def test_auth_verify_otp_demo_bypass():
    """
    Tests that verifying the OTP code using a demo session successfully
    bypasses Cognito cloud verification, issues the mock JWT cookies/payload, and succeeds.
    """
    if os.getenv("DEMO_LOGIN_ENABLED") != "true":
        pytest.skip("DEMO_LOGIN_ENABLED is not set to true, skipping demo auth test")

    # Generate a demo verification session payload
    verify_payload = {
        "email": DEMO_EMAIL,
        "otp": "123456",  # Any 6-digit code is accepted in demo mode
        "session": f"demo-session-{DEMO_EMAIL}"
    }
    
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/verify-otp", json=verify_payload)
        
        assert response.status_code == 200, f"OTP verification failed: {response.text}"
        json_data = response.json()
        assert json_data.get("token_in_cookie") is True
        assert json_data.get("expires_in") == 43200
        
        # Assert session cookies are set correctly (HttpOnly security standard)
        assert "ac_session" in response.cookies