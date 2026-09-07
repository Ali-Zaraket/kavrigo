"""Identity provider abstraction.

``AGENTS.md`` step 4 calls for a Clerk integration *abstraction*. Clerk issues standard JWTs, so
the verifier here is built on RFC 7515/7517/7519 (JWS, JWK, JWT) rather than on Clerk-specific
endpoints. That keeps the code honest — nothing is invented from recollection of a vendor API —
and it means Auth0, WorkOS or any OIDC issuer can be configured in later without a rewrite
(``MASTER_BUILD_SPEC.md`` §21).

What *is* vendor-specific is configuration, not code: the issuer, the JWKS URL, the audience,
and which claim carries the organization. Those must be confirmed against current Clerk
documentation before the first real token is verified; the defaults here are standard claim
names, not asserted Clerk behaviour.

Security properties this module is responsible for:

* signature verification against a key from the issuer's JWKS, with the algorithm allowlisted
  (never taken from the token header alone — that is the ``alg=none`` and HMAC-confusion class
  of bug);
* issuer, audience and expiry validation;
* bounded, cached JWKS fetching so a key rotation does not become an outage or a hot loop;
* no token, key or claim payload in logs.
"""

from __future__ import annotations

import time
from typing import Any, Protocol, runtime_checkable

import httpx
import jwt
from jwt import PyJWKClient
from pydantic import BaseModel, ConfigDict

from kavrigo_api.logging import get_logger

__all__ = [
    "DevIdentityProvider",
    "ExternalIdentity",
    "IdentityProvider",
    "IdentityVerificationError",
    "JwksIdentityProvider",
]

_log = get_logger(__name__)

#: Asymmetric algorithms only. A symmetric algorithm in this list would let anyone holding the
#: public JWKS key mint valid tokens (the classic RS256 -> HS256 confusion attack).
ALLOWED_ALGORITHMS: tuple[str, ...] = ("RS256", "RS384", "RS512", "ES256", "ES384")


class IdentityVerificationError(Exception):
    """Raised when a token cannot be verified. The reason is logged, never returned."""


class ExternalIdentity(BaseModel):
    """What the identity provider asserts about the caller.

    Deliberately minimal: the platform stores its own user record keyed on ``subject`` and does
    not mirror provider profile data it has no use for.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str
    """The ``sub`` claim. The stable external identifier for this account."""

    email: str | None = None
    session_id: str | None = None
    organization_id: str | None = None
    """Present when the provider models organizations. Mapped to a workspace, never trusted as
    one: membership is always re-checked against our own tables."""

    mfa_verified: bool = False
    issued_at: int | None = None
    expires_at: int | None = None


@runtime_checkable
class IdentityProvider(Protocol):
    """Verifies a bearer token and returns the asserted identity."""

    async def verify(self, token: str) -> ExternalIdentity: ...


class JwksIdentityProvider:
    """Verifies JWTs against an issuer's JWKS.

    Configure with the issuer, JWKS URL and audience from the identity provider's dashboard.
    Claim names are configurable because providers differ in where they put the organization and
    the second-factor assertion.
    """

    def __init__(
        self,
        *,
        issuer: str,
        jwks_url: str,
        audience: str | None = None,
        organization_claim: str = "org_id",
        mfa_claim: str = "mfa",
        email_claim: str = "email",
        session_claim: str = "sid",
        leeway_seconds: int = 30,
        cache_lifespan_seconds: int = 600,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._organization_claim = organization_claim
        self._mfa_claim = mfa_claim
        self._email_claim = email_claim
        self._session_claim = session_claim
        self._leeway = leeway_seconds
        # PyJWKClient caches keys and re-fetches on an unknown `kid`, which is what makes key
        # rotation survivable without either an outage or a fetch on every request.
        self._jwk_client = PyJWKClient(
            jwks_url,
            cache_keys=True,
            lifespan=cache_lifespan_seconds,
            timeout=5,
        )

    async def verify(self, token: str) -> ExternalIdentity:
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(ALLOWED_ALGORITHMS),
                issuer=self._issuer,
                audience=self._audience,
                leeway=self._leeway,
                options={
                    "require": ["exp", "iat", "sub"],
                    "verify_aud": self._audience is not None,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_iss": True,
                    "verify_signature": True,
                },
            )
        except (jwt.PyJWTError, httpx.HTTPError, ValueError) as exc:
            # The reason is useful to us and useful to an attacker. It is logged and not returned.
            _log.warning("token_verification_failed", error_type=type(exc).__name__)
            raise IdentityVerificationError("token verification failed") from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise IdentityVerificationError("token has no usable subject claim")

        return ExternalIdentity(
            subject=subject,
            email=_optional_str(claims.get(self._email_claim)),
            session_id=_optional_str(claims.get(self._session_claim)),
            organization_id=_optional_str(claims.get(self._organization_claim)),
            mfa_verified=_coerce_mfa(claims.get(self._mfa_claim)),
            issued_at=_optional_int(claims.get("iat")),
            expires_at=_optional_int(claims.get("exp")),
        )


class DevIdentityProvider:
    """Accepts ``dev:<subject>[:mfa]`` tokens for local development and tests.

    This exists so the control plane can be exercised end to end without a Clerk instance. It is
    refused outside the ``local`` environment by ``Settings`` — a development bypass reachable in
    a deployed environment is an authentication bypass, not a convenience.
    """

    PREFIX = "dev:"

    def __init__(self, *, allowed_subjects: frozenset[str] | None = None) -> None:
        self._allowed = allowed_subjects

    async def verify(self, token: str) -> ExternalIdentity:
        if not token.startswith(self.PREFIX):
            raise IdentityVerificationError("not a development token")
        parts = token.removeprefix(self.PREFIX).split(":")
        subject = parts[0]
        if not subject:
            raise IdentityVerificationError("development token has no subject")
        if self._allowed is not None and subject not in self._allowed:
            raise IdentityVerificationError("subject is not in the development allowlist")
        mfa = len(parts) > 1 and parts[1] == "mfa"
        now = int(time.time())
        return ExternalIdentity(
            subject=subject,
            email=f"{subject}@dev.invalid",
            session_id=f"devsess_{subject}",
            mfa_verified=mfa,
            issued_at=now,
            expires_at=now + 3600,
        )


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _coerce_mfa(value: Any) -> bool:
    """Interpret a second-factor claim conservatively.

    Providers express this differently — a boolean, a count of verified factors, or a list of
    completed authentication methods. Anything unrecognised is treated as *not* verified,
    because guessing in the permissive direction would silently unlock the operations that MFA
    is meant to protect.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value > 0
    if isinstance(value, str):
        return value.lower() in {"true", "verified", "mfa"}
    if isinstance(value, list):
        return len(value) > 1
    return False
