"""PENDING placeholders. Owner: Nguyen Ngoc Kim. Nothing here is implemented or passing."""

import pytest

pytestmark = pytest.mark.pending


@pytest.mark.skip(reason="PENDING(Kim): scenario 5 - access denied by policy, gate not called")
def test_access_denied() -> None: ...


@pytest.mark.skip(reason="PENDING(Kim): scenario 6 - gate command failure is not attendance")
def test_gate_command_failure() -> None: ...
