# Node profiles

A profile gives a fleet node its own persona, Skills, and MCP-server roster —
layered on top of the generic bootstrap `install-node.sh` already does
(auth, tmux, watchdog, fleetbroker). This is a thin convenience over Claude
Code's own per-instance config model: each node already has its own
`~/.claude/CLAUDE.md` and MCP roster regardless of fleetbroker, a profile
just makes seeding them repeatable instead of hand-copied.

## Layout

```
profiles/<name>/
  CLAUDE.md    # optional - copied verbatim to ~/.claude/CLAUDE.md
  skills/      # optional - each subdirectory copied to ~/.claude/skills/
  mcp.json     # optional - list of MCP servers to register, see below
```

All three pieces are optional and independent — a profile that only sets a
persona with no skills or MCP servers is fine.

## `mcp.json` format

```json
[
  {
    "name": "github",
    "scope": "user",
    "json": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}" }
    }
  }
]
```

Each entry is fed straight to `claude mcp add-json <name> <json> --scope
<scope>`. `json` is whatever that command expects (stdio/SSE/HTTP/WebSocket
server config).

## Secrets: never in the profile file

`${VAR}` placeholders anywhere inside an entry's `json` block are substituted
from the installer's own environment at install time — **the profile itself
must never contain a real token**, only the placeholder name. Export the real
value in the shell that runs `install-node.sh` (or source a
`gitignore`d/untracked env file first):

```bash
export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_...
./install-node.sh MyNode --profile profiles/github-triage
```

If a placeholder's variable isn't set, the installer fails loudly on that
entry rather than silently registering a broken/literal `${VAR}` value.

This means `profiles/` itself is entirely safe to commit to git — it holds
structure and placeholder names only, never secret values.

## `example/` is a template, not a real profile

`profiles/example/` demonstrates the shape (a persona line, one trivial
Skill, one MCP server with a placeholder). Copy it as a starting point for a
real role-specific profile rather than using it as-is.
