from __future__ import annotations

import json
import threading
import urllib.request

from tests.fake_ollama import FIXTURE_MODEL, make_server


def test_tags_endpoint_is_deterministic() -> None:
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(  # noqa: S310 - test server is loopback-only
            f"http://127.0.0.1:{server.server_port}/api/tags", timeout=1
        ) as response:
            payload = json.load(response)
        assert payload == {"models": [{"name": FIXTURE_MODEL}]}
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
