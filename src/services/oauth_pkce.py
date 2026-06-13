from __future__ import annotations

_pkce_verifiers: dict[str, str] = {}


def store_pkce_verifier(state: str, verifier: str) -> None:
    _pkce_verifiers[state] = verifier


def pop_pkce_verifier(state: str) -> str | None:
    return _pkce_verifiers.pop(state, None)
