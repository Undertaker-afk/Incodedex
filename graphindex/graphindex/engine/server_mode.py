"""Optional server mode: run models behind llama-cpp-python's OpenAI server.

``python -m llama_cpp.server`` exposes an OpenAI-compatible HTTP API. This
helper can launch such a server for a given GGUF and provides a tiny client for
``/v1/embeddings`` and ``/v1/chat/completions`` so the same models can be shared
across processes or machines. The in-process :class:`LlamaEngine` is the default
and faster path; server mode is provided for power users / distributed setups.
"""

from __future__ import annotations

import atexit
import subprocess
import sys
import threading
import time
from urllib import request, error
import json


# Track every llama_cpp.server subprocess we spawn so an atexit hook can stop
# them. Without this, a crashed parent leaves orphan model servers running
# (holding GPU/RAM + ports) until the user kills them manually.
_PROCS: list[subprocess.Popen] = []
_PROCS_LOCK = threading.Lock()


def _stop_all() -> None:
    with _PROCS_LOCK:
        procs = list(_PROCS)
        _PROCS.clear()
    for p in procs:
        if p.poll() is not None:
            continue
        try:
            p.terminate()
        except Exception:
            pass
    for p in procs:
        if p.poll() is not None:
            continue
        try:
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


atexit.register(_stop_all)


def start_server(model_path: str, host: str = "127.0.0.1", port: int = 8081,
                 embedding: bool = False, extra: list[str] | None = None
                 ) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "llama_cpp.server", "--model", model_path,
           "--host", host, "--port", str(port)]
    if embedding:
        cmd += ["--embedding", "true"]
    if extra:
        cmd += extra
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with _PROCS_LOCK:
        _PROCS.append(proc)
    return proc


def stop_server(proc: subprocess.Popen) -> None:
    """Explicitly terminate a server started by :func:`start_server`."""
    with _PROCS_LOCK:
        if proc in _PROCS:
            _PROCS.remove(proc)
    if proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def wait_ready(host: str, port: int, timeout: float = 60.0) -> bool:
    url = f"http://{host}:{port}/v1/models"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (error.URLError, OSError):
            time.sleep(1.0)
    return False


class OpenAIClient:
    """Minimal client for a llama_cpp.server endpoint (stdlib only)."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = request.Request(self.base_url + path, data=data,
                              headers={"Content-Type": "application/json"})
        with request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = self._post("/v1/embeddings", {"input": texts})
        return [d["embedding"] for d in out["data"]]

    def chat(self, system: str, user: str, max_tokens: int = 128) -> str:
        out = self._post("/v1/chat/completions", {
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "max_tokens": max_tokens, "temperature": 0.2})
        return out["choices"][0]["message"]["content"].strip()
