"""Regression tests for MCPRuntimeService sync/async bridge."""

import asyncio
import os
import sys

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.services.mcp_runtime import MCPRuntimeService


async def async_value():
    await asyncio.sleep(0)
    return 42


async def async_failure():
    await asyncio.sleep(0)
    raise ValueError("bridge failure")


service = MCPRuntimeService({})
assert service._run_async(async_value()) == 42


async def run_inside_existing_loop():
    assert service._run_async(async_value()) == 42
    try:
        service._run_async(async_failure())
    except ValueError as exc:
        assert str(exc) == "bridge failure"
    else:
        raise AssertionError("expected ValueError from bridged coroutine")


asyncio.run(run_inside_existing_loop())

print("test_mcp_runtime_bridge: OK")