import json
import os
import re
import shlex
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def read(*parts):
    with open(os.path.join(REPO, *parts)) as f:
        return f.read()


def servers():
    manifest = json.loads(read("plugins", "cortex-qa-tools", ".mcp.json"))
    return {name: [s["command"], *s["args"]] for name, s in manifest["mcpServers"].items()}


class ServerDocsMatchManifest(unittest.TestCase):
    """The OpenCode and Codex install docs copy .mcp.json by hand; keep them in step."""

    def test_opencode_snippet(self):
        block = re.search(r'```json\n(\{\n  "mcp".*?)\n```', read(".opencode", "INSTALL.md"), re.S)
        if block is None:
            self.fail("mcp snippet missing from .opencode/INSTALL.md")
        snippet = json.loads(block.group(1))["mcp"]
        self.assertEqual({name: s["command"] for name, s in snippet.items()}, servers())

    def test_codex_fallback_commands(self):
        lines = re.findall(r"^codex mcp add (.+)$", read(".codex", "INSTALL.md"), re.M)
        commands = {}
        for line in lines:
            name, sep, *command = shlex.split(line)
            self.assertEqual(sep, "--")
            commands[name] = command
        self.assertEqual(commands, servers())


if __name__ == "__main__":
    unittest.main()
