"""Third-party provider adapters (LLM, payments, maps, messaging, storage).

Each concern exposes an interface plus concrete providers selected by env vars.
When credentials are missing a clearly-labelled null/console provider is used
and reports `configured = False`; it never fakes a successful external call.
Populated from Phase 8 onwards.
"""
