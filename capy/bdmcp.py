"""Thin client for Bright Data's remote MCP server (same tools the TrueForge agent uses)."""
import asyncio
import json
import os
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from capy.config import settings


def _url(groups: str | None = None) -> str:
    url = f"https://mcp.brightdata.com/mcp?token={settings.brightdata_api_key}"
    return f"{url}&groups={groups}" if groups else url


@asynccontextmanager
async def session(groups: str | None = None):
    async with streamable_http_client(_url(groups)) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            yield s


def text_of(result) -> str:
    """Join the text parts of an MCP tool result."""
    return "\n".join(getattr(c, "text", "") for c in result.content)


async def call(s: ClientSession, tool: str, **args) -> str:
    res = await s.call_tool(tool, args)
    out = text_of(res)
    if res.is_error:
        raise RuntimeError(f"{tool} failed: {out[:500]}")
    return out


async def _main():
    async with session("browser,advanced_scraping") as s:
        tools = await s.list_tools()
        print(json.dumps(sorted(t.name for t in tools.tools)))


if __name__ == "__main__":
    asyncio.run(_main())
