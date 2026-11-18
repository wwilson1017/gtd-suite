"""The REST API (api_v1.py) calls the MCP tools in-process with ``mcp.call_tool``,
so REST mirrors every tool with no second copy. That holds only if FastMCP's own
call path runs our middleware (_AppsOn: an off app is refused) and hands back the
tool's structured dict. This pins both, for the FastMCP the lock file installs."""

import pytest
from fastmcp.exceptions import ToolError

from backend import lists, mcp_server, service
from backend.tests.test_mcp import anyio_backend, app  # noqa: F401 (fixtures)

pytestmark = pytest.mark.anyio


async def _call(list_id: int, on: list[str], name: str, args: dict):
    resets = mcp_server._list_id.set(list_id), mcp_server._apps_on.set(on)
    try:
        return await mcp_server.mcp.call_tool(name, args)
    finally:
        mcp_server._apps_on.reset(resets[1])
        mcp_server._list_id.reset(resets[0])


async def test_call_tool_runs_the_apps_on_middleware_and_returns_the_structured_dict(app):
    list_id = lists.create_list("UTC")["list_id"]

    result = await _call(list_id, ["todo"], "todo_create", {"title": "Call the dentist"})
    assert result.structured_content["todo"]["title"] == "Call the dentist"

    # The same call with Todo off: _AppsOn refuses it before the tool runs.
    with pytest.raises(ToolError, match="is off for this account"):
        await _call(list_id, ["brain"], "todo_create", {"title": "Never made"})
    assert [t["title"] for t in service.list_todos(list_id)] == ["Call the dentist"]
