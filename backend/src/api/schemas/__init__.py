"""Request and response bodies for the HTTP surface, one module per component.

Only ``api.routes`` imports these (import-linter contract ``http-schemas``).
Responses are built from component views, never entities (ADR 0013).
"""
