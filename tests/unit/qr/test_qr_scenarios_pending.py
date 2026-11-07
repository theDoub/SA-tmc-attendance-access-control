"""PENDING placeholders. Owner: Nguyen Nhat Hieu. Nothing here is implemented or passing."""

import pytest

pytestmark = pytest.mark.pending


@pytest.mark.skip(reason="PENDING(Hieu): scenario 1 - valid QR accepted (blocked by OD-01/OD-02)")
def test_valid_qr() -> None: ...


@pytest.mark.skip(reason="PENDING(Hieu): scenario 2 - invalid signature rejected")
def test_invalid_signature() -> None: ...


@pytest.mark.skip(reason="PENDING(Hieu): scenario 3 - expired QR rejected")
def test_expired_qr() -> None: ...


@pytest.mark.skip(reason="PENDING(Hieu): scenario 4 - replayed QR rejected (OD-08)")
def test_replay_attack() -> None: ...


@pytest.mark.skip(reason="PENDING(Hieu): extra - malformed QR rejected without opening gate")
def test_malformed_qr() -> None: ...
