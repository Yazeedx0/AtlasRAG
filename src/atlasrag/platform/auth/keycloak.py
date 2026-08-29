import asyncio
import json
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx
import jwt
from jwt import InvalidTokenError

from atlasrag.contracts.authentication import (
    AuthenticatedIdentity,
    TokenVerificationError,
)


class KeycloakTokenVerifier:
    """Verify Keycloak access tokens using the realm's published JWKS."""

    def __init__(
        self,
        *,
        issuer: str,
        discovery_url: str,
        audience: str,
        algorithms: Sequence[str] = ("RS256",),
        timeout_seconds: float,
        jwks_cache_ttl_seconds: float,
        jwks_refresh_cooldown_seconds: float,
        http_client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not issuer:
            raise ValueError("Keycloak issuer must not be empty")
        if not discovery_url:
            raise ValueError("Keycloak discovery URL must not be empty")
        if not audience:
            raise ValueError("Keycloak audience must not be empty")
        if not algorithms:
            raise ValueError("At least one JWT algorithm is required")
        if timeout_seconds <= 0:
            raise ValueError("Keycloak timeout must be positive")
        if jwks_cache_ttl_seconds <= 0:
            raise ValueError("JWKS cache TTL must be positive")
        if jwks_refresh_cooldown_seconds < 0:
            raise ValueError("JWKS refresh cooldown must not be negative")

        self._issuer = issuer.rstrip("/")
        self._discovery_url = discovery_url.rstrip("/")
        self._audience = audience
        self._algorithms = tuple(algorithms)
        self._jwks_cache_ttl_seconds = jwks_cache_ttl_seconds
        self._jwks_refresh_cooldown_seconds = jwks_refresh_cooldown_seconds
        self._clock = clock
        self._client = http_client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = http_client is None
        self._refresh_lock = asyncio.Lock()
        self._keys: dict[str, Mapping[str, Any]] = {}
        self._jwks_expires_at = 0.0
        self._last_refresh_at = 0.0

    async def verify(self, token: str) -> AuthenticatedIdentity:
        """Validate a bearer access token and return its trusted identity claims."""
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as error:
            raise TokenVerificationError("Malformed token header") from error

        algorithm = header.get("alg")
        key_id = header.get("kid")
        if not isinstance(algorithm, str) or algorithm not in self._algorithms:
            raise TokenVerificationError("Token uses an unsupported signing algorithm")
        if not isinstance(key_id, str) or not key_id:
            raise TokenVerificationError("Token does not contain a signing key id")

        key = await self._key_for_id(key_id)
        if key is None:
            raise TokenVerificationError("Token signing key is not trusted")

        if key.get("alg") not in (None, algorithm):
            raise TokenVerificationError("Token signing key algorithm does not match")

        try:
            claims = jwt.decode(
                token,
                jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key)),
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "sub"]},
            )
        except (InvalidTokenError, TypeError, ValueError) as error:
            raise TokenVerificationError("Token validation failed") from error

        return self._identity_from_claims(claims)

    async def aclose(self) -> None:
        """Close the HTTP client when this verifier owns it."""
        if self._owns_client:
            await self._client.aclose()

    async def _key_for_id(self, key_id: str) -> Mapping[str, Any] | None:
        await self._refresh_jwks()
        key = self._keys.get(key_id)
        if key is not None:
            return key

        await self._refresh_jwks(force=True)
        return self._keys.get(key_id)

    async def _refresh_jwks(self, *, force: bool = False) -> None:
        now = self._clock()
        if not force and self._keys and now < self._jwks_expires_at:
            return
        if force and self._last_refresh_at:
            if now - self._last_refresh_at < self._jwks_refresh_cooldown_seconds:
                return

        async with self._refresh_lock:
            now = self._clock()
            if not force and self._keys and now < self._jwks_expires_at:
                return
            if force and self._last_refresh_at:
                if now - self._last_refresh_at < self._jwks_refresh_cooldown_seconds:
                    return

            discovery = await self._get_json(self._discovery_url)
            jwks_uri = discovery.get("jwks_uri")
            if not isinstance(jwks_uri, str) or not jwks_uri:
                raise TokenVerificationError("Keycloak discovery has no JWKS URI")

            jwks = await self._get_json(jwks_uri)
            raw_keys = jwks.get("keys")
            if not isinstance(raw_keys, list):
                raise TokenVerificationError("Keycloak JWKS has an invalid key list")

            keys: dict[str, Mapping[str, Any]] = {}
            for raw_key in raw_keys:
                if not isinstance(raw_key, Mapping):
                    continue
                raw_key_id = raw_key.get("kid")
                if isinstance(raw_key_id, str) and raw_key_id:
                    keys[raw_key_id] = raw_key

            if not keys:
                raise TokenVerificationError("Keycloak JWKS contains no usable keys")

            self._keys = keys
            self._jwks_expires_at = now + self._jwks_cache_ttl_seconds
            self._last_refresh_at = now

    async def _get_json(self, url: str) -> Mapping[str, Any]:
        try:
            response = await self._client.get(url)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise TokenVerificationError("Keycloak metadata is unavailable") from error

        if not isinstance(payload, Mapping):
            raise TokenVerificationError("Keycloak metadata has an invalid format")
        return payload

    def _identity_from_claims(self, claims: Mapping[str, Any]) -> AuthenticatedIdentity:
        issuer = claims.get("iss")
        subject = claims.get("sub")
        if not isinstance(issuer, str) or not issuer:
            raise TokenVerificationError("Token has no issuer")
        if not isinstance(subject, str) or not subject:
            raise TokenVerificationError("Token has no subject")

        email = claims.get("email")
        email_verified = claims.get("email_verified")
        username = claims.get("preferred_username")
        display_name = claims.get("name")

        return AuthenticatedIdentity(
            issuer=issuer,
            subject=subject,
            email=email if isinstance(email, str) else None,
            email_verified=email_verified if isinstance(email_verified, bool) else None,
            username=username if isinstance(username, str) else None,
            display_name=display_name if isinstance(display_name, str) else None,
        )
