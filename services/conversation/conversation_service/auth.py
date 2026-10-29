"""Bearer-token verification.

The conversation service validates the same HS256 token the core service issues and
uses only its `sub` (the customer id). It holds no customer data of its own.
"""
from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, Request

from .config import Settings, get_settings
from .errors import AuthenticationError, AuthorisationError


@dataclass(frozen=True)
class Principal:
    customer_id: str


def get_principal(request: Request, settings: Settings = Depends(get_settings)) -> Principal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError()

    try:
        claims = jwt.decode(
            token.strip(),
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "sub", "scope"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Token is invalid.") from exc

    if claims.get("scope") != "customer":
        raise AuthorisationError("This endpoint requires a customer token.")
    return Principal(customer_id=str(claims["sub"]))
