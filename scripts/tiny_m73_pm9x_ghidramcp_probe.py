#!/usr/bin/env python3
"""Over-the-wire PM9X GhidraMCP probe.

This intentionally avoids MCP client dependencies so it can run both locally
through an SSH tunnel and directly on tiny-m73.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


EXPECTED_PROGRAMS = [
    "/PM97/PM97.EXE",
    "/PM97/MANAGER.EXE",
    "/PM97/DBASEWIN.EXE",
    "/PM98/PM98.EXE",
    "/PM98/MANAGER.EXE",
    "/PM98/Dbasewin.exe",
    "/PM99/PM99.EXE",
    "/PM99/MANAGPRE.EXE",
    "/PM99/DBASEPRE.EXE",
]

REQUIRED_TOOLS = {
    "list_programs",
    "manage_project",
    "search_memory",
    "read_functions",
    "read_memory_blocks",
    "decompile_code",
}


class ProbeError(RuntimeError):
    pass


class McpHttpClient:
    def __init__(self, url: str, timeout: float = 180.0) -> None:
        self.url = url
        self.timeout = timeout
        self.next_id = 1

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            body["params"] = params
        raw = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=raw,
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "User-Agent": "pm9x-ghidramcp-probe/1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read().decode("utf-8", errors="replace")
                content_type = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProbeError(f"HTTP {exc.code} from {self.url}: {detail}") from exc
        except OSError as exc:
            raise ProbeError(f"Could not reach {self.url}: {exc}") from exc

        message = self._parse_response(data, content_type, request_id)
        if "error" in message:
            raise ProbeError(f"JSON-RPC error for {method}: {message['error']}")
        return message

    @staticmethod
    def _parse_response(data: str, content_type: str, request_id: int) -> dict[str, Any]:
        if "text/event-stream" not in content_type:
            return json.loads(data)

        candidates: list[dict[str, Any]] = []
        for line in data.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            parsed = json.loads(payload)
            if parsed.get("id") == request_id:
                return parsed
            candidates.append(parsed)
        if candidates:
            return candidates[-1]
        raise ProbeError("No JSON-RPC payload found in event-stream response")

    def initialize(self) -> None:
        self.rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pm9x-ghidramcp-probe", "version": "1"},
            },
        )
        try:
            self.rpc("notifications/initialized")
        except ProbeError:
            # Stateless HTTP servers do not always require or return a response
            # for the initialized notification.
            pass

    def list_tools(self) -> set[str]:
        msg = self.rpc("tools/list")
        tools = msg.get("result", {}).get("tools", [])
        return {tool.get("name", "") for tool in tools}

    def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None, expect_error: bool = False
    ) -> dict[str, Any]:
        msg = self.rpc("tools/call", {"name": name, "arguments": arguments or {}})
        result = msg.get("result", {})
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            payload = structured
        else:
            text = "\n".join(
                item.get("text", "")
                for item in result.get("content", [])
                if item.get("type") == "text"
            )
            try:
                payload = json.loads(text) if text.strip() else {}
            except json.JSONDecodeError as exc:
                raise ProbeError(f"{name} returned non-JSON text: {text[:500]}") from exc

        is_error = bool(result.get("isError")) or payload.get("success") is False
        if is_error and not expect_error:
            raise ProbeError(f"{name} failed: {json.dumps(payload, sort_keys=True)[:1000]}")
        if expect_error and not is_error:
            raise ProbeError(f"{name} was expected to fail but succeeded")
        return payload


def normalize_project_path(path: str) -> str:
    value = path.strip().replace("\\", "/")
    if not value.startswith("/"):
        value = "/" + value
    return value


def first_function_address(client: McpHttpClient, file_name: str) -> str:
    payload = client.call_tool("read_functions", {"file_name": file_name, "page_size": 1})
    rows = payload.get("data") or []
    if not rows:
        raise ProbeError(f"No functions returned for {file_name}")
    address = rows[0].get("entry_point") or rows[0].get("start_address")
    if not address:
        raise ProbeError(f"First function for {file_name} has no address: {rows[0]}")
    return str(address)


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    client = McpHttpClient(args.url, timeout=args.timeout)
    started = time.time()
    report: dict[str, Any] = {
        "url": args.url,
        "started_at_epoch": started,
        "checks": {},
    }

    client.initialize()
    report["checks"]["initialize"] = True

    tools = client.list_tools()
    missing_tools = sorted(REQUIRED_TOOLS - tools)
    if missing_tools:
        raise ProbeError(f"Missing MCP tools: {', '.join(missing_tools)}")
    report["checks"]["tools"] = sorted(tools)

    programs_payload = client.call_tool("list_programs", {"page_size": 100})
    program_rows = programs_payload.get("data") or []
    program_paths = {normalize_project_path(str(row.get("path", ""))) for row in program_rows}
    missing_programs = [path for path in EXPECTED_PROGRAMS if path not in program_paths]
    if missing_programs:
        raise ProbeError(f"Missing Ghidra project programs: {', '.join(missing_programs)}")
    report["checks"]["program_paths"] = sorted(program_paths)

    for path in ["/PM97/MANAGER.EXE", "/PM98/MANAGER.EXE", "/PM99/MANAGPRE.EXE"]:
        payload = client.call_tool(
            "manage_project", {"file_name": path, "action": "get_program_info"}
        )
        data = payload.get("data") or {}
        if not data:
            raise ProbeError(f"manage_project returned no program info for {path}")
        report["checks"][f"program_info:{path}"] = {
            "name": data.get("name"),
            "format": data.get("format"),
            "image_base": data.get("image_base"),
        }

    ambiguous = client.call_tool(
        "manage_project",
        {"file_name": "MANAGER.EXE", "action": "get_program_info"},
        expect_error=True,
    )
    ambiguous_text = json.dumps(ambiguous, sort_keys=True)
    if "multiple program files" not in ambiguous_text:
        raise ProbeError(f"Bare MANAGER.EXE did not produce expected ambiguity: {ambiguous_text}")
    report["checks"]["bare_manager_ambiguous"] = True

    for path in ["/PM97/MANAGER.EXE", "/PM98/MANAGER.EXE", "/PM99/MANAGPRE.EXE"]:
        blocks = client.call_tool("read_memory_blocks", {"file_name": path, "page_size": 3})
        if not blocks.get("data"):
            raise ProbeError(f"read_memory_blocks returned no data for {path}")
        report["checks"][f"memory_blocks:{path}"] = len(blocks["data"])

        function_address = first_function_address(client, path)
        report["checks"][f"first_function:{path}"] = function_address

        if not args.skip_decompile:
            decomp = client.call_tool(
                "decompile_code",
                {
                    "file_name": path,
                    "target_type": "address",
                    "target_value": function_address,
                    "timeout": args.decompile_timeout,
                },
            )
            if not decomp.get("data"):
                raise ProbeError(f"decompile_code returned no data for {path} at {function_address}")
            report["checks"][f"decompile:{path}"] = True

    report["finished_at_epoch"] = time.time()
    report["duration_seconds"] = round(report["finished_at_epoch"] - started, 3)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18080/mcp")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--decompile-timeout", type=int, default=30)
    parser.add_argument("--skip-decompile", action="store_true")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    try:
        report = run_probe(args)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
