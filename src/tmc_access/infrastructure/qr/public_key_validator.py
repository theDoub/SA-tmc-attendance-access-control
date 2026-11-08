"""Verify-only Ed25519 simulation profile; see docs/issue-analysis.md."""

import base64
import binascii
import json
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from tmc_access.domain.interfaces.qr import ReplayGuard
from tmc_access.domain.models.qr import (
    QrValidationOutcome as Outcome,
    QrValidationResult,
    VerifiedCredential,
)


class PublicKeyQrValidator:
    """Requires explicit public keys and replay port; unconfigured instances deny."""

    def __init__(self, public_keys=None, replay_guard: ReplayGuard | None = None):
        self._keys = dict(public_keys or {})
        self._replay = replay_guard

    def validate(self, raw_payload: str, station_id: str, now: datetime) -> QrValidationResult:
        def reject(outcome):
            return QrValidationResult(outcome)

        if now.tzinfo is None or now.utcoffset() is None:
            return reject(Outcome.CLOCK_UNRELIABLE)
        try:
            if not isinstance(raw_payload, str) or len(raw_payload) > 8192:
                return reject(Outcome.MALFORMED)
            body, signature = raw_payload.split('.')

            def decode(value):
                return base64.b64decode(value + '=' * (-len(value) % 4),
                                        altchars=b'-_', validate=True)

            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError('duplicate claim')
                    result[key] = value
                return result

            claims = json.loads(decode(body), object_pairs_hook=unique)
            if not isinstance(claims, dict):
                return reject(Outcome.MALFORMED)
            for name in ('sub', 'jti', 'kid', 'aud'):
                if not isinstance(claims.get(name), str) or not claims[name]:
                    return reject(Outcome.MALFORMED)
            for name in ('iat', 'exp'):
                if type(claims.get(name)) is not int:
                    return reject(Outcome.MALFORMED)
            issued = datetime.fromtimestamp(claims['iat'], UTC)
            expires = datetime.fromtimestamp(claims['exp'], UTC)
            sig = decode(signature)
        except (ValueError, TypeError, OverflowError, OSError, binascii.Error):
            return reject(Outcome.MALFORMED)
        key = self._keys.get(claims['kid'])
        if key is None:
            return reject(Outcome.UNKNOWN_KEY)
        if not isinstance(key, Ed25519PublicKey):
            from tmc_access.domain.errors import QrError
            raise QrError('Invalid verification key configuration')
        try:
            key.verify(sig, body.encode('ascii'))
        except InvalidSignature:
            return reject(Outcome.INVALID_SIGNATURE)
        if expires <= issued:
            return reject(Outcome.MALFORMED)
        if now >= expires:
            return reject(Outcome.EXPIRED)
        if now < issued:
            return reject(Outcome.CLOCK_UNRELIABLE)
        if claims['aud'] != station_id:
            return reject(Outcome.WRONG_AUDIENCE)
        if self._replay is None:
            from tmc_access.domain.errors import StorageError
            raise StorageError('Replay guard is required')
        if not self._replay.check_and_record(claims['jti'], expires, now):
            return reject(Outcome.REPLAYED)
        return QrValidationResult(Outcome.VALID, VerifiedCredential(
            claims['sub'], claims['jti'], claims['kid'], issued, expires))
