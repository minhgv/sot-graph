"""Cross-platform CI smoke checks for built distributions.

Subcommands (run from the repo root after `uv build`):

    mcp       Install the built wheel into an isolated environment and verify
              that the MCP server initializes with the expected version.
    template  Install the built wheel and run `sot setup --harness omp`.

Replaces the previous inline `python -c "..."` steps in ci.yml: PowerShell on
windows-latest does not treat backslash-escaped quotes as Bash does, which
broke the embedded code string. A committed script avoids shell quoting
entirely.
"""

from __future__ import annotations

import glob
import subprocess
import sys
import tempfile

MCP_VERIFY_CODE = '''import os
import tempfile

from sot_graph.db import Database
from sot_graph.mcp_service import McpService
from sot_graph.mcp_server import create_server

f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
db_path = f.name
f.close()
db = Database(db_path)
db.close()
service = McpService(db_path, ".")
try:
    s = create_server(service)
    assert s._sot_initialization_options.server_version == "0.3.0"
    print("MCP server verified:", s._sot_initialization_options.server_version)
finally:
    service.close()
    os.unlink(db_path)
'''


def _wheel() -> str:
    wheels = sorted(glob.glob("dist/*.whl"))
    if not wheels:
        sys.exit("no dist/*.whl found; run `uv build` first")
    return wheels[0]


def _run(args: list[str]) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, check=True)


def mcp() -> None:
    _run(
        [
            "uv", "run", "--isolated",
            "--with", "mcp>=1.3",
            "--with", _wheel(),
            "python", "-c", MCP_VERIFY_CODE,
        ]
    )


def template() -> None:
    with tempfile.TemporaryDirectory() as root:
        _run(
            [
                "uv", "run", "--isolated",
                "--with", _wheel(),
                "sot", "--root", root,
                "setup", "--harness", "omp", "--workspace-only",
            ]
        )
    print("Template smoke test passed")


def main() -> None:
    commands = {"mcp": mcp, "template": template}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: {sys.argv[0]} {{mcp|template}}")
    commands[sys.argv[1]]()


if __name__ == "__main__":
    main()
