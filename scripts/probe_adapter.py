"""Run the adapter directly, without MCP or a worker subprocess."""

import os
import sys

os.environ["CHEMCAD_MCP_DEBUG"] = "1"
from chemcad_mcp.worker import Automation

automation = Automation()
try:
    print(automation.open_simulation(sys.argv[1]), flush=True)
    print(automation.summary(), flush=True)
    print(automation.read_stream(1), flush=True)
finally:
    automation.disconnect()
