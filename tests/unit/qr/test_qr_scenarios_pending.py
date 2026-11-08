"""Real cryptographic tests using ephemeral synthetic keys; no private key fixtures."""

import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tmc_access.domain.errors import StorageError
from tmc_access.infrastructure.qr.public_key_validator import PublicKeyQrValidator
from tmc_access.infrastructure.qr.replay_guard import ReplayGuardStore


@pytest.fixture
def profile():
    key = Ed25519PrivateKey.generate()
    guard = ReplayGuardStore()
    validator = PublicKeyQrValidator({'test-v1': key.public_key()}, guard)

    def token(**changes):
        claims = dict(sub='synthetic-user', jti='synthetic-id', kid='test-v1',
                      aud='station-test', iat=1000, exp=1060)
        claims.update(changes)
        body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b'=')
        signature = base64.urlsafe_b64encode(key.sign(body)).rstrip(b'=')
        return (body + b'.' + signature).decode()

    return validator, token


@pytest.mark.parametrize(('changes', 'at', 'expected'), [
    ({}, 1000, 'VALID'),
    ({}, 1059, 'VALID'),
    ({}, 1060, 'EXPIRED'),
    ({}, 1061, 'EXPIRED'),
    ({}, 999, 'CLOCK_UNRELIABLE'),
    ({'aud': 'other'}, 1001, 'WRONG_AUDIENCE'),
    ({'kid': 'unknown'}, 1001, 'UNKNOWN_KEY'),
    ({'exp': 1000}, 1001, 'MALFORMED'),
    ({'iat': True}, 1001, 'MALFORMED'),
    ({'jti': ''}, 1001, 'MALFORMED'),
])
def test_claims(profile, changes, at, expected):
    validator, token = profile
    result = validator.validate(token(**changes), 'station-test', datetime.fromtimestamp(at, UTC))
    assert result.outcome == expected
    assert (result.credential is not None) == (expected == 'VALID')


def test_signature(profile):
    validator, token = profile
    body, signature = token().split('.')
    signature = ('A' if signature[0] != 'A' else 'B') + signature[1:]
    now = datetime.fromtimestamp(1001, UTC)
    assert validator.validate(body + '.' + signature, 'station-test', now).outcome == 'INVALID_SIGNATURE'
    assert validator.validate(token(), 'station-test', now).outcome == 'VALID'


@pytest.mark.parametrize('raw', ['', 'a.b.c', '!.!', 'e30=.AA=='])
def test_malformed(profile, raw):
    assert profile[0].validate(raw, 'station-test', datetime.now(UTC)).outcome == 'MALFORMED'


def test_replay_atomic(profile):
    validator, token = profile
    raw = token()
    now = datetime.fromtimestamp(1001, UTC)
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: validator.validate(raw, 'station-test', now).outcome,
                                 range(16)))
    assert outcomes.count('VALID') == 1
    assert outcomes.count('REPLAYED') == 15


def test_storage_failure(profile):
    class BrokenGuard:
        def check_and_record(self, *args):
            raise StorageError('synthetic storage failure')

    validator, token = profile
    validator._replay = BrokenGuard()
    with pytest.raises(StorageError):
        validator.validate(token(), 'station-test', datetime.fromtimestamp(1001, UTC))


def test_naive_clock(profile):
    assert profile[0].validate(profile[1](), 'station-test', datetime(2026, 1, 1)).outcome == 'CLOCK_UNRELIABLE'
