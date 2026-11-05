"""Optional client and connection check for a standalone bot backend."""

import argparse
import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx2
from dotenv import load_dotenv
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


DEFAULT_URL = "https://www.mcpsatudataaceh.web.id/mcp"


class ConnectionCheckError(Exception):
    """A message safe to print without including credentials."""


@asynccontextmanager
async def connect_mcp():
    """Open a Streamable HTTP client using the backend's environment."""
    token = os.getenv("SDA_MCP_TOKEN", "").strip()
    if not token:
        raise ConnectionCheckError("Isi SDA_MCP_TOKEN dengan token MCP dari dashboard.")

    url = os.getenv("SDA_MCP_URL") or DEFAULT_URL
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise ConnectionCheckError("SDA_MCP_URL tidak valid.") from None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ConnectionCheckError("SDA_MCP_URL harus berupa endpoint HTTPS tanpa userinfo.")

    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx2.Timeout(30, connect=10),
    ) as http_client:
        async with Client(streamable_http_client(url, http_client=http_client)) as client:
            yield client


async def call_data(client, name, arguments):
    result = await client.call_tool(name, arguments)
    if result.is_error or not isinstance(result.structured_content, dict):
        raise ConnectionCheckError(f"{name}: tool gagal atau respons terstruktur tidak tersedia.")
    return result.structured_content


async def check_connection(portal_only):
    failure = None
    async with connect_mcp() as client:
        try:
            await check_tools(client, portal_only)
        except ConnectionCheckError as error:
            failure = error
    if failure is not None:
        raise failure


async def check_tools(client, portal_only):
    tools = await client.list_tools()
    required = {"search", "fetch"}
    if not portal_only:
        required.update(("bps_endpoints", "bps_request"))
    missing = required - {tool.name for tool in tools.tools}
    if missing:
        raise ConnectionCheckError(f"Tool belum tersedia: {', '.join(sorted(missing))}.")
    print("Koneksi MCP berhasil. Tool yang diperlukan tersedia.")

    portal = await call_data(client, "search", {"query": "inflasi", "limit": 3})
    if portal.get("message") or not isinstance(portal.get("results"), list):
        raise ConnectionCheckError("Pencarian katalog Aceh gagal. Periksa status layanan dan batas permintaan.")
    print(f"Portal Satu Data Aceh berhasil merespons ({len(portal['results'])} hasil sampel).")
    if portal_only:
        return

    bps = await call_data(client, "bps_request", {
        "operation": "listDomains",
        "parameters": {"type": "prov"},
    })
    if bps.get("ok") is not True:
        error = bps.get("error")
        if error == "missing_credential":
            raise ConnectionCheckError("Simpan API key BPS di dashboard akun penerbit token MCP.")
        if error == "credential_rejected":
            raise ConnectionCheckError("BPS menolak API key. Periksa izin dan masa berlaku key di BPS.")
        raise ConnectionCheckError("BPS gagal merespons sampel listDomains. Periksa hasil uji BPS di dashboard.")
    print("Web API BPS berhasil merespons operasi sampel listDomains.")


def main():
    parser = argparse.ArgumentParser(description="Periksa koneksi bot ke MCP Satu Data Aceh.")
    parser.add_argument("--portal-only", action="store_true", help="Lewati uji Web API BPS.")
    args = parser.parse_args()
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    try:
        asyncio.run(check_connection(args.portal_only))
    except ConnectionCheckError as error:
        print(error, file=sys.stderr)
        return 1
    except Exception:
        print("Koneksi MCP gagal. Periksa URL, jaringan, dan token MCP di backend.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
