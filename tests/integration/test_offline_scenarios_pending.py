"""PENDING placeholders. Owner: Bui Doan Minh Nhat. Nothing here is implemented or passing."""

import pytest

pytestmark = [pytest.mark.pending, pytest.mark.integration]


@pytest.mark.skip(reason="PENDING(Nhat): scenario 7 - network disconnection keeps gate working")
def test_network_disconnection() -> None: ...
