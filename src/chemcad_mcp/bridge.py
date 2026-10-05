"""Asynchronous JSON pipe to a dedicated COM apartment process."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys


class WorkerBridge:
    def __init__(self, timeout: float | None = None):
        self.timeout = (
            timeout
            if timeout is not None
            else float(os.environ.get("CHEMCAD_MCP_TIMEOUT", "180"))
        )
        if self.timeout <= 0:
            raise ValueError("CHEMCAD_MCP_TIMEOUT must be positive")
        self.process = None
        self.lock = asyncio.Lock()

    async def _start(self):
        if sys.platform != "win32":
            raise RuntimeError("Live CHEMCAD automation requires Windows")
        if self.process is None or self.process.returncode is not None:
            self.process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                "-m",
                "chemcad_mcp.worker",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=None,
                creationflags=subprocess.CREATE_NO_WINDOW,
                limit=4 * 1024 * 1024,
            )

    async def request(self, operation: str, **arguments):
        async with self.lock:
            await self._start()
            try:
                async with asyncio.timeout(self.timeout):
                    payload = json.dumps(
                        {"operation": operation, "arguments": arguments},
                        allow_nan=False,
                    )
                    self.process.stdin.write((payload + "\n").encode("utf-8"))
                    await self.process.stdin.drain()
                    line = await self.process.stdout.readline()
                    if not line:
                        raise RuntimeError(
                            "CHEMCAD COM worker exited unexpectedly; reconnect before continuing"
                        )
                    response = json.loads(line)
            except TimeoutError:
                # Discard the worker so a late response cannot be consumed by another request.
                await self._stop()
                raise RuntimeError(
                    f"CHEMCAD exceeded {self.timeout:g}s. The worker was disconnected; unsaved changes may be lost. Reopen the simulation before continuing."
                ) from None
            except asyncio.CancelledError:
                await self._stop()
                raise
            except (BrokenPipeError, ConnectionResetError, json.JSONDecodeError):
                await self._stop()
                raise RuntimeError("CHEMCAD COM worker connection failed") from None
            if not response["ok"]:
                suffix = f" ({response['hresult']})" if "hresult" in response else ""
                raise RuntimeError(response["error"] + suffix)
            return response["result"]

    async def _stop(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.returncode is None:
            if process.stdin is not None:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except TimeoutError:
                if process.returncode is None:
                    process.kill()
                await process.wait()

    async def close(self):
        async with self.lock:
            await self._stop()
