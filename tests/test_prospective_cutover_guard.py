"""Prospective state ownership is exclusive across migration."""
import pytest
from scripts.prospective_cutover_guard import require_owner
from scripts.state_store import StateError


class Store:
    def __init__(self, status):
        self.status=status
    def read(self, name):
        assert name=="prospective"
        return {"status":self.status}


def test_legacy_only_when_uninitialized():
    assert require_owner("legacy",Store("uninitialized"))=="legacy"
    with pytest.raises(StateError,match="legacy main"):
        require_owner("legacy",Store("available"))


def test_canonical_requires_authority_and_unknown_fails():
    assert require_owner("canonical",Store("available"))=="canonical"
    with pytest.raises(StateError,match="bootstrap"):
        require_owner("canonical",Store("uninitialized"))
    with pytest.raises(StateError):
        require_owner("legacy",Store("corrupt"))
    with pytest.raises(StateError):
        require_owner("broken",Store("available"))
