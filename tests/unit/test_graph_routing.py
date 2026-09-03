"""Routing decisions in src/pipeline/graph.py."""
from __future__ import annotations

import pytest

from src.pipeline import graph as g


class _S:
    def __init__(self, required):
        self.approval_required = required


@pytest.mark.parametrize(
    "state, required, expected",
    [
        ({}, True, "approve"),
        ({}, False, "wait_for_slot"),
        ({"dry_run": True}, True, "wait_for_slot"),        # preview -> nothing to approve
        ({"dry_run": False}, True, "approve"),
        ({"skip_approval": True}, True, "wait_for_slot"),   # dashboard "Publish" = the approval
        ({"skip_approval": True, "dry_run": False}, True, "wait_for_slot"),
    ],
)
def test_route_schedule(monkeypatch, state, required, expected):
    monkeypatch.setattr(g, "get_settings", lambda: _S(required), raising=False)
    # _route_schedule imports get_settings lazily from src.config
    monkeypatch.setattr("src.config.get_settings", lambda: _S(required))
    assert g._route_schedule(state) == expected


def test_route_approve_rejected_goes_to_finalize():
    assert g._route_approve({"approval_status": "rejected"}) == "finalize"
    assert g._route_approve({"approval_status": "timeout"}) == "finalize"
    assert g._route_approve({"approval_status": "approved"}) == "wait_for_slot"
