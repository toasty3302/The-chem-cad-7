import asyncio
import sys

import pytest

from chemcad_mcp.bridge import WorkerBridge

DUMMY_WORKER = """
import json, sys, time
for line in sys.stdin:
    request = json.loads(line)
    args = request['arguments']
    time.sleep(args.get('delay', 0))
    print(json.dumps({'ok': True, 'result': args.get('value')}), flush=True)
"""


class PipeBridge(WorkerBridge):
    async def _start(self):
        if self.process is None:
            self.process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                "-c",
                DUMMY_WORKER,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
            )


def test_concurrent_requests_do_not_mix_responses():
    async def scenario():
        bridge = PipeBridge(timeout=5)
        try:
            values = await asyncio.gather(
                *(bridge.request("test", value=index) for index in range(10))
            )
            assert values == list(range(10))
        finally:
            await bridge.close()

    asyncio.run(scenario())


def test_timeout_discards_worker_and_late_response():
    async def scenario():
        bridge = PipeBridge(timeout=0.1)
        try:
            with pytest.raises(RuntimeError, match="exceeded"):
                await bridge.request("test", value="late", delay=0.5)
            assert bridge.process is None
            bridge.timeout = 5
            assert await bridge.request("test", value="new") == "new"
        finally:
            await bridge.close()

    asyncio.run(scenario())
