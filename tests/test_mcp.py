import io
from unittest.mock import patch

import pytest

from cognition.mcp.server import build


async def test_mcp_catalog_and_prediction_have_no_control_side_effects(platform):
    pytest.importorskip("mcp")
    from mcp import Client

    state = platform.connector.disturb("kiln", "heat_load")

    class Response:
        def __enter__(self):
            return io.StringIO("[" + state.model_dump_json() + "]")

        def __exit__(self, *args):
            pass

    with patch("cognition.mcp.server.urlopen", return_value=Response()):
        async with Client(build()) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools.tools} == {
                "list_plants",
                "predict_action",
                "discover_capabilities",
            }
            result = await client.call_tool("predict_action", {"plant_id": "kiln", "value": 36})
            assert result.structured_content["revision"] == state.revision
            assert result.structured_content["prediction"]["recovered"]
    assert platform.store.plant("kiln") == state
