"""
Authentication routes – login flow for broker providers.

Zerodha Kite Connect login flow:
1. GET /auth/login-url  → returns the Kite Connect OAuth URL
2. User logs in on Zerodha's site
3. Zerodha redirects browser to GET /auth/redirect?request_token=xxx&status=success
4. Backend exchanges request_token for access_token
5. Browser is redirected to the frontend dashboard
"""

from __future__ import annotations

import logging
import os

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.api.deps import ProviderDep, ConfigDep
from app.providers.types import Credentials

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Frontend URL — where to redirect after successful login
FRONTEND_URL = os.environ.get("TRADE_FRONTEND_URL", "https://localhost:3000")


class LoginURLResponse(BaseModel):
    login_url: str
    provider: str


class CallbackRequest(BaseModel):
    request_token: str
    api_key: str = ""
    api_secret: str = ""


class SessionResponse(BaseModel):
    user_id: str
    user_name: str
    email: str
    broker: str
    access_token: str


def _get_credentials() -> tuple[str, str]:
    """Read API key and secret from environment."""
    api_key = os.environ.get("TRADE_ZERODHA_API_KEY", "")
    api_secret = os.environ.get("TRADE_ZERODHA_API_SECRET", "")
    return api_key, api_secret


@router.get("/login-url", response_model=LoginURLResponse)
async def get_login_url(provider: ProviderDep):
    """Generate the broker login URL."""
    info = provider.get_provider_info()
    try:
        login_url = provider.get_login_url()
    except Exception:
        # Fallback: build Kite Connect URL from env
        api_key, _ = _get_credentials()
        if not api_key:
            raise HTTPException(
                status_code=500,
                detail="TRADE_ZERODHA_API_KEY not configured in .env",
            )
        login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
    return LoginURLResponse(login_url=login_url, provider=info.name)


@router.get("/redirect")
async def handle_redirect(
    request_token: str = Query(..., description="One-time token from Zerodha after login"),
    status: str = Query("success"),
    provider: ProviderDep = None,
):
    """
    Redirect URL handler — Zerodha redirects the user's browser here after login.

    This is a GET endpoint (browser redirect), NOT a POST.
    Reads request_token from query params, exchanges it for access_token,
    then redirects the user to the frontend dashboard.

    Configure this URL in Kite Connect Developer Console:
      Redirect URL = https://localhost:8000/api/auth/redirect
    """
    if status != "success":
        return RedirectResponse(url=f"{FRONTEND_URL}?auth_error=login_failed")

    api_key, api_secret = _get_credentials()
    if not api_key or not api_secret:
        return RedirectResponse(url=f"{FRONTEND_URL}?auth_error=missing_credentials")

    try:
        credentials = Credentials(api_key=api_key, api_secret=api_secret)
        session = await provider.authenticate(
            credentials=credentials,
            request_token=request_token,
        )
        # Persist session to database for restart recovery
        try:
            from app.services.session_store import save_session
            await save_session(
                provider="zerodha",
                access_token=session.access_token,
                user_id=session.user_id,
                meta={"user_name": session.user_name, "email": session.email},
            )
        except Exception as persist_err:
            logger.warning("Failed to persist session to DB: %s", persist_err)

        # Redirect to frontend with success indicator
        return RedirectResponse(
            url=f"{FRONTEND_URL}?auth=success&user={session.user_id}"
        )
    except Exception as e:
        return RedirectResponse(
            url=f"{FRONTEND_URL}?auth_error={str(e)[:100]}"
        )


@router.post("/callback", response_model=SessionResponse)
async def handle_callback(body: CallbackRequest, provider: ProviderDep):
    """
    Manual token exchange endpoint (for programmatic/API use).
    The /auth/redirect GET endpoint handles the browser flow automatically.
    """
    api_key, api_secret = _get_credentials()
    try:
        credentials = Credentials(
            api_key=body.api_key or api_key,
            api_secret=body.api_secret or api_secret,
        )
        session = await provider.authenticate(
            credentials=credentials,
            request_token=body.request_token,
        )
        # Persist session to database for restart recovery
        try:
            from app.services.session_store import save_session
            provider_name = provider.get_provider_info().name
            await save_session(
                provider=provider_name,
                access_token=session.access_token,
                user_id=session.user_id,
                meta={"user_name": session.user_name, "email": session.email},
            )
        except Exception as persist_err:
            logger.warning("Failed to persist session to DB: %s", persist_err)

        return SessionResponse(
            user_id=session.user_id,
            user_name=session.user_name,
            email=session.email,
            broker=session.broker,
            access_token=session.access_token,
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/session")
async def get_session(provider: ProviderDep):
    """Check if the current session is authenticated."""
    try:
        health = await provider.health_check()
        result = {"authenticated": health.healthy, "latency_ms": health.latency_ms}

        # Include session metadata if available
        if health.healthy:
            try:
                from app.services.session_store import load_active_session
                provider_name = provider.get_provider_info().name
                saved = await load_active_session(provider_name)
                if saved:
                    result["user_id"] = saved.get("user_id")
                    result["expires_at"] = (
                        saved["expires_at"].isoformat()
                        if saved.get("expires_at") else None
                    )
            except Exception:
                pass  # DB may not be available; session endpoint still works

        return result
    except Exception:
        return {"authenticated": False, "latency_ms": None}
