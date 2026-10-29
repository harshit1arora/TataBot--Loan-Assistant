"""Authentication, authorisation and signed download tokens.

Three token types, all HS256 (swap to RS256 + JWKS when the key lives in a KMS):
  * customer access token — sub = customer_id, scope = "customer"
  * service token        — sub = client_id,     scope = "service"  (agents -> core)
  * download token       — short-lived HMAC over a document id, single purpose
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Literal

import jwt
from fastapi import Depends, Request

from .config import Settings, get_settings
from .errors import AuthenticationError, AuthorisationError

Scope = Literal["customer", "service"]


@dataclass(frozen=True)
class Principal:
    subject: str
    scope: Scope
    token_id: str

    @property
    def customer_id(self) -> str:
        if self.scope != "customer":
            raise AuthorisationError("This endpoint requires a customer token.")
        return self.subject


def _encode(claims: dict, settings: Settings) -> str:
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def issue_customer_token(customer_id: str, settings: Settings) -> tuple[str, int]:
    ttl = settings.access_token_ttl_seconds
    now = int(time.time())
    token = _encode(
        {
            "sub": customer_id,
            "scope": "customer",
            "iat": now,
            "nbf": now,
            "exp": now + ttl,
            "jti": secrets.token_hex(8),
            "iss": "core-service",
            "aud": "tatabot-api",
        },
        settings,
    )
    return token, ttl


def issue_service_token(client_id: str, settings: Settings) -> tuple[str, int]:
    ttl = settings.service_token_ttl_seconds
    now = int(time.time())
    token = _encode(
        {
            "sub": client_id,
            "scope": "service",
            "iat": now,
            "nbf": now,
            "exp": now + ttl,
            "jti": secrets.token_hex(8),
            "iss": "core-service",
            "aud": "tatabot-api",
        },
        settings,
    )
    return token, ttl


def decode_token(token: str, settings: Settings) -> Principal:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience="tatabot-api",
            issuer="core-service",
            options={"require": ["exp", "iat", "sub", "scope"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Token is invalid.") from exc

    scope = claims.get("scope")
    if scope not in ("customer", "service"):
        raise AuthenticationError("Token scope is not recognised.")
    return Principal(subject=str(claims["sub"]), scope=scope, token_id=str(claims.get("jti", "")))


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError()
    return token.strip()


def get_principal(request: Request, settings: Settings = Depends(get_settings)) -> Principal:
    return decode_token(_bearer(request), settings)


def require_customer(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.scope != "customer":
        raise AuthorisationError("This endpoint requires a customer token.")
    return principal


def require_service(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.scope != "service":
        raise AuthorisationError("This endpoint requires a service token.")
    return principal


# --------------------------------------------------------------------------
# Signed download URLs — the object store stand-in for S3 presigned GETs.
# --------------------------------------------------------------------------
def _sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def create_download_token(document_id: str, customer_id: str, settings: Settings) -> str:
    payload = json.dumps(
        {"doc": document_id, "sub": customer_id, "exp": int(time.time()) + settings.signed_url_ttl_seconds},
        separators=(",", ":"),
    ).encode()
    body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{body}.{_sign(payload, settings.jwt_secret)}"


def verify_download_token(token: str, settings: Settings) -> tuple[str, str]:
    try:
        body, signature = token.split(".", 1)
        padded = body + "=" * (-len(body) % 4)
        payload = base64.urlsafe_b64decode(padded.encode())
    except Exception as exc:  # noqa: BLE001 - any malformed token is simply invalid
        raise AuthenticationError("Download link is malformed.") from exc

    if not hmac.compare_digest(_sign(payload, settings.jwt_secret), signature):
        raise AuthenticationError("Download link signature is invalid.")

    claims = json.loads(payload)
    if int(claims.get("exp", 0)) < int(time.time()):
        raise AuthenticationError("Download link has expired.")
    return str(claims["doc"]), str(claims["sub"])


def verify_service_credentials(
    client_id: str, client_secret: str, settings: Settings
) -> None:
    if not (
        hmac.compare_digest(client_id, settings.service_client_id)
        and hmac.compare_digest(client_secret, settings.service_client_secret)
    ):
        raise AuthenticationError("Client credentials are invalid.")
