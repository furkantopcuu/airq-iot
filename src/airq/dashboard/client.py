"""Tiny HTTP client for the airq API: the dashboard reads ONLY through this (spec 8.7)."""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_URL = "http://127.0.0.1:8000"


class ApiError(RuntimeError):
    """Raised when the API is unreachable or answers with an error status."""


class ApiClient:
    def __init__(self, base_url: str | None = None, timeout_s: float = 5.0):
        self.base_url = (base_url or os.environ.get("AIRQ_API_URL") or DEFAULT_URL).rstrip("/")
        self._http = httpx.Client(timeout=timeout_s)

    def get(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        try:
            resp = self._http.get(f"{self.base_url}{path}", params=clean)
        except httpx.HTTPError as exc:
            raise ApiError(f"API'ye ulaşılamıyor ({self.base_url}): {exc}") from exc
        if resp.status_code >= 400:
            detail = resp.json().get("detail", resp.text) if resp.content else resp.status_code
            raise ApiError(f"{path}: {resp.status_code} {detail}")
        return resp.json()

    def post(self, path: str, body: dict | None = None) -> Any:
        """POST JSON (Senaryo Kontrol). Refusals (422 / 504 ...) raise ApiError with the reason."""
        try:
            resp = self._http.post(f"{self.base_url}{path}", json=body or {})
        except httpx.HTTPError as exc:
            raise ApiError(f"API'ye ulaşılamıyor ({self.base_url}): {exc}") from exc
        if resp.status_code >= 400:
            detail = resp.json().get("detail", resp.text) if resp.content else resp.status_code
            raise ApiError(f"{path}: {resp.status_code} {detail}")
        return resp.json()

    def url(self, path: str) -> str:
        """Absolute URL (e.g. for st.image of /figures/<name>)."""
        return f"{self.base_url}{path}"

    def get_bytes(self, path: str) -> bytes | None:
        """Raw body (e.g. a PNG) or None when it does not exist / the API is unreachable."""
        try:
            resp = self._http.get(f"{self.base_url}{path}")
        except httpx.HTTPError:
            return None
        return resp.content if resp.status_code == 200 else None
