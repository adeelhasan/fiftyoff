"""CLAUDE.md rule 3: no test may reach the Keepa API. Any socket connect fails the test."""

import socket

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def guard(*args, **kwargs):
        raise RuntimeError("network access attempted during tests")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)
