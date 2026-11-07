"""PENDING placeholders. Owner: Bui Doan Minh Nhat. Nothing here is implemented or passing."""

import pytest

pytestmark = [pytest.mark.pending, pytest.mark.integration]


@pytest.mark.skip(reason="PENDING(Nhat): scenario 7 - network disconnection keeps gate working")
def test_network_disconnection() -> None: ...


@pytest.mark.skip(reason="PENDING(Nhat): scenario 8 - record + outbox persisted atomically")
def test_local_event_persistence() -> None: ...


@pytest.mark.skip(reason="PENDING(Nhat): scenario 9 - reconnection flushes pending outbox")
def test_reconnection_and_synchronization() -> None: ...


@pytest.mark.skip(reason="PENDING(Nhat): scenario 10 - duplicate transaction_id ingestion")
def test_duplicate_event_ingestion() -> None: ...
