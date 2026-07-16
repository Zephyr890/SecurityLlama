"""Deterministic, local-only Ollama-compatible service used by tests and demos."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

FIXTURE_MODEL = "fixture-model"


def assistant_payload(fixture: str) -> dict[str, Any]:
    """Return an Ollama chat envelope for a named deterministic fixture."""
    response: dict[str, Any] = {
        "schema_version": "1",
        "answer": "A TCP connection can fail before or during the handshake.",
        "proposed_command": None,
        "command_explanation": None,
        "risk": "none",
        "requires_root": False,
        "network_effect": "none",
        "target_candidates": [],
        "warnings": [],
        "assumptions": ["No packet capture was supplied."],
    }
    if fixture == "proposal":
        response.update(
            proposed_command="curl -I --max-time 5 https://10.10.10.25/",
            command_explanation="Fetch only the HTTP response headers with a short timeout.",
            risk="low",
            network_effect="active",
            target_candidates=["10.10.10.25"],
        )
    elif fixture == "control_sequences":
        response["answer"] = "\x1b[31mcolored\x1b[0m\x1b]0;host-title\x07 answer"
    content = "{not-json" if fixture == "malformed_json" else json.dumps(response)
    return {
        "model": FIXTURE_MODEL,
        "created_at": "2026-07-16T00:00:00Z",
        "message": {"role": "assistant", "content": content},
        "done": True,
    }


class FakeOllamaHandler(BaseHTTPRequestHandler):
    """Minimal `/api/tags` and `/api/chat` handler."""

    fixture: ClassVar[str] = "success"
    requests_seen: ClassVar[list[dict[str, Any]]] = []

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def _send_json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/tags":
            models = [] if self.fixture == "missing_model" else [{"name": FIXTURE_MODEL}]
            self._send_json(HTTPStatus.OK, {"models": models})
            return
        if self.path == "/_requests":
            self._send_json(HTTPStatus.OK, self.requests_seen)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/chat":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        try:
            request = json.loads(raw_body)
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON"})
            return
        self.requests_seen.append(request)
        if self.fixture == "timeout":
            time.sleep(2.0)
        self._send_json(HTTPStatus.OK, assistant_payload(self.fixture))


def make_server(host: str, port: int, fixture: str = "success") -> ThreadingHTTPServer:
    """Create a configured fake server without starting its event loop."""
    handler = type("ConfiguredFakeOllamaHandler", (FakeOllamaHandler,), {"fixture": fixture})
    return ThreadingHTTPServer((host, port), handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11435)
    parser.add_argument(
        "--fixture",
        choices=[
            "success",
            "proposal",
            "malformed_json",
            "timeout",
            "missing_model",
            "control_sequences",
        ],
        default="success",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = make_server(args.host, args.port, args.fixture)
    print(f"fake Ollama listening on http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
