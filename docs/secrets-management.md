# Secrets management pattern (optional, external to fleetbroker)

## What fleetbroker itself does

A node profile's `mcp.json` (see
[`provision/profiles/README.md`](../provision/profiles/README.md)) never
holds a real credential - every value that would be one is written as a
`${VAR}` placeholder, substituted from `install-node.sh`'s own environment
at install time. If the referenced variable isn't set, the installer fails
that entry loudly rather than registering a broken or literal `${VAR}`
value. This means the profile files themselves - and the fleet's git
history - never contain a secret, regardless of how many real credentials a
node's MCP roster needs.

Fleetbroker does not care where those environment variables come from. That
choice is yours; this doc just describes a pattern that fits cleanly.

## The pattern: a scriptable secrets manager as the source

Any self-hosted or cloud secrets manager with a CLI that can be scripted -
a self-hosted password manager (e.g. a Bitwarden-compatible server), a
cloud password manager's CLI, or a dedicated secrets engine (HashiCorp
Vault, etc.) - can populate the environment right before provisioning:

```bash
# illustrative - the exact command depends on which tool you use
export GITHUB_PERSONAL_ACCESS_TOKEN="$(your-secrets-cli get github-pat)"
export N8N_API_KEY="$(your-secrets-cli get n8n-api-key)"

./install-node.sh MyNode --profile profiles/my-role
```

A small wrapper script that unlocks the vault once, fetches everything a
given profile needs, exports it, and calls `install-node.sh` is enough -
there's no need for fleetbroker to know the secrets manager exists at all.

## Why this is worth doing instead of scattering plaintext files

Without something like this, per-node credentials end up scattered across
whatever config files each MCP server or integration happens to read from -
no central inventory, no single place to rotate a credential, no audit
trail. Centralizing the actual values in a secrets manager (and keeping
only placeholder names in git) gives you one inventory and one place to
rotate, without changing anything about how fleetbroker itself works.

## The one thing this doesn't solve

Centralizing secrets moves the "something must exist in plaintext
somewhere" problem up one level, it doesn't eliminate it - a node still
needs *some* credential to unlock the secrets manager itself. The
improvement is real (one bootstrap credential per node instead of N
scattered ones), just not magic. Treat that one bootstrap credential with
the same care you'd give any of the secrets it unlocks.
