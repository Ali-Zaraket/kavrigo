"""Identity verification: signature, algorithm, issuer, audience and expiry."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from kavrigo_api.auth.identity import (
    ALLOWED_ALGORITHMS,
    DevIdentityProvider,
    IdentityVerificationError,
    JwksIdentityProvider,
)

ISSUER = "https://identity.example.test"
AUDIENCE = "kavrigo-api"


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch, rsa_key: rsa.RSAPrivateKey) -> JwksIdentityProvider:
    """A provider whose JWKS lookup returns the local test key.

    The network is not involved: only the verification logic is under test.
    """
    p = JwksIdentityProvider(
        issuer=ISSUER, jwks_url=f"{ISSUER}/.well-known/jwks.json", audience=AUDIENCE
    )

    class _Key:
        key = rsa_key.public_key()

    monkeypatch.setattr(p._jwk_client, "get_signing_key_from_jwt", lambda _token: _Key())
    return p


def _token(rsa_key: rsa.RSAPrivateKey, *, kid: str | None = None, **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": "user_abc",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 600,
        "email": "person@example.test",
        "sid": "sess_1",
    }
    claims.update(overrides)
    algorithm = overrides.pop("_alg", "RS256")
    return jwt.encode(claims, rsa_key, algorithm=algorithm, headers={"kid": kid} if kid else None)


class TestJwksVerification:
    async def test_removed_signing_key_is_not_trusted_after_jwks_refresh(
        self, rsa_key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = JwksIdentityProvider(
            issuer=ISSUER, jwks_url=f"{ISSUER}/.well-known/jwks.json", audience=AUDIENCE
        )
        rotated_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        active_keys = [SimpleNamespace(key=rsa_key.public_key(), key_id="rotation")]
        monkeypatch.setattr(
            provider._jwk_client, "get_signing_keys", lambda refresh=False: active_keys
        )

        old_token = _token(rsa_key, kid="rotation")
        assert (await provider.verify(old_token)).subject == "user_abc"

        # A refreshed JWKS now serves a different public key under the same kid. A stale
        # per-key LRU would still accept the old signature and reject the new one.
        active_keys[0] = SimpleNamespace(key=rotated_key.public_key(), key_id="rotation")
        with pytest.raises(IdentityVerificationError):
            await provider.verify(old_token)
        assert (await provider.verify(_token(rotated_key, kid="rotation"))).subject == "user_abc"

    async def test_slow_jwks_lookup_does_not_block_other_coroutines(
        self,
        provider: JwksIdentityProvider,
        rsa_key: rsa.RSAPrivateKey,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lookup = provider._jwk_client.get_signing_key_from_jwt
        started = threading.Event()
        release = threading.Event()

        def slow_lookup(token: str) -> Any:
            started.set()
            if not release.wait(timeout=2):
                raise TimeoutError("test JWKS lookup was not released")
            return lookup(token)

        monkeypatch.setattr(provider._jwk_client, "get_signing_key_from_jwt", slow_lookup)
        verification = asyncio.create_task(provider.verify(_token(rsa_key)))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 0.5), timeout=1)
            await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
            assert not verification.done()
        finally:
            release.set()
        assert (await verification).subject == "user_abc"

    async def test_a_valid_token_is_accepted(
        self, provider: JwksIdentityProvider, rsa_key: rsa.RSAPrivateKey
    ) -> None:
        identity = await provider.verify(_token(rsa_key))
        assert identity.subject == "user_abc"
        assert identity.email == "person@example.test"
        assert identity.session_id == "sess_1"

    async def test_an_expired_token_is_rejected(
        self, provider: JwksIdentityProvider, rsa_key: rsa.RSAPrivateKey
    ) -> None:
        now = int(time.time())
        with pytest.raises(IdentityVerificationError):
            await provider.verify(_token(rsa_key, iat=now - 7200, exp=now - 3600))

    async def test_a_token_from_another_issuer_is_rejected(
        self, provider: JwksIdentityProvider, rsa_key: rsa.RSAPrivateKey
    ) -> None:
        with pytest.raises(IdentityVerificationError):
            await provider.verify(_token(rsa_key, iss="https://attacker.example"))

    async def test_a_token_for_another_audience_is_rejected(
        self, provider: JwksIdentityProvider, rsa_key: rsa.RSAPrivateKey
    ) -> None:
        with pytest.raises(IdentityVerificationError):
            await provider.verify(_token(rsa_key, aud="some-other-service"))

    async def test_a_token_signed_by_another_key_is_rejected(
        self, provider: JwksIdentityProvider
    ) -> None:
        attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with pytest.raises(IdentityVerificationError):
            await provider.verify(_token(attacker_key))

    async def test_an_unsigned_token_is_rejected(self, provider: JwksIdentityProvider) -> None:
        """The ``alg=none`` class of attack."""
        now = int(time.time())
        unsigned = jwt.encode(
            {"sub": "user_abc", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 600},
            key="",
            algorithm="none",
        )
        with pytest.raises(IdentityVerificationError):
            await provider.verify(unsigned)

    async def test_a_token_with_no_subject_is_rejected(
        self, provider: JwksIdentityProvider, rsa_key: rsa.RSAPrivateKey
    ) -> None:
        with pytest.raises(IdentityVerificationError):
            await provider.verify(_token(rsa_key, sub=""))

    async def test_garbage_is_rejected(self, provider: JwksIdentityProvider) -> None:
        with pytest.raises(IdentityVerificationError):
            await provider.verify("not-a-token")

    def test_only_asymmetric_algorithms_are_allowed(self) -> None:
        """An HMAC algorithm here would let anyone holding the public JWKS key mint tokens."""
        assert all(not alg.startswith("HS") for alg in ALLOWED_ALGORITHMS)
        assert "none" not in ALLOWED_ALGORITHMS


class TestMfaClaimInterpretation:
    async def test_boolean_true_is_verified(
        self, provider: JwksIdentityProvider, rsa_key: rsa.RSAPrivateKey
    ) -> None:
        identity = await provider.verify(_token(rsa_key, mfa=True))
        assert identity.mfa_verified

    async def test_absent_claim_is_not_verified(
        self, provider: JwksIdentityProvider, rsa_key: rsa.RSAPrivateKey
    ) -> None:
        assert not (await provider.verify(_token(rsa_key))).mfa_verified

    async def test_unrecognised_shapes_default_to_not_verified(
        self, provider: JwksIdentityProvider, rsa_key: rsa.RSAPrivateKey
    ) -> None:
        """Guessing permissively would silently unlock exactly what MFA protects."""
        for value in ({"nested": "object"}, "maybe", 0, []):
            identity = await provider.verify(_token(rsa_key, mfa=value))
            assert not identity.mfa_verified


class TestDevProvider:
    async def test_dev_tokens_resolve_to_a_subject(self) -> None:
        identity = await DevIdentityProvider().verify("dev:alice")
        assert identity.subject == "alice"
        assert not identity.mfa_verified

    async def test_dev_tokens_can_assert_mfa(self) -> None:
        assert (await DevIdentityProvider().verify("dev:alice:mfa")).mfa_verified

    async def test_non_dev_tokens_are_rejected(self) -> None:
        with pytest.raises(IdentityVerificationError):
            await DevIdentityProvider().verify("eyJhbGciOi.something.else")

    async def test_an_allowlist_can_restrict_subjects(self) -> None:
        provider = DevIdentityProvider(allowed_subjects=frozenset({"alice"}))
        assert (await provider.verify("dev:alice")).subject == "alice"
        with pytest.raises(IdentityVerificationError):
            await provider.verify("dev:mallory")
