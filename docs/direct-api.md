# Direct-API probe: dropping the Home Assistant dependency

## What changed

The original quota policy (`fleetbroker.probes.ha_quota`) reads usage numbers
from Home Assistant sensors, which are themselves populated by a HACS
integration ([`trickv/hass-claude-usage`](https://github.com/trickv/hass-claude-usage))
that polls Anthropic's own undocumented usage endpoint on your behalf. That's
two extra systems (Home Assistant, and that specific HACS integration) that
add nothing to the actual policy - they were only in the chain because that's
where this data already happened to be available in the deployment this
project was extracted from.

`fleetbroker.probes.anthropic_usage` calls the same endpoint directly:

```
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <access_token>
anthropic-beta: oauth-2025-04-20
```

using the access token the `claude` CLI **already has** in
`~/.claude/.credentials.json` - the same token used for Remote Control. No
separate OAuth client, no separate login, no Home Assistant. Every fleet node
already needs a working `claude auth login` (see `docs/auth.md`), so this
probe adds zero new setup steps. `decide()`/`prepare_state()`/`build_body()`
are re-exported unchanged from `ha_quota` - only the data source differs, the
policy is identical (verified: `test_anthropic_usage_probe.py` asserts these
are literally the same function objects, not a re-implementation that could
drift).

## How this was found

`hass-claude-usage`'s source (`custom_components/hass_claude_usage/const.py`
and `__init__.py`) was read directly to find the endpoint URL, the required
`anthropic-beta` header, and the OAuth scope (`user:profile`) it requests for
its own, separately-registered OAuth client. Checking `~/.claude/.credentials.json`
showed the `claude` CLI's own token already carries `user:profile` among its
scopes (alongside `user:inference`, `user:mcp_servers`, etc.) - and a live
test call with that exact token against the endpoint returned `200 OK` with
real usage data. Anthropic's backend accepts the token regardless of which
registered OAuth client originally issued it, as long as the scope is present.

## Tradeoffs, stated plainly

- **This is an undocumented, unofficial endpoint.** It's what claude.ai's own
  web UI uses internally, reverse-engineered by the HACS integration's
  author, not a published/versioned API. It can change or disappear without
  notice. `ha_quota` remains a supported, equally-tested alternative for
  anyone who wants a layer of insulation (or who already has the HA
  integration running for other reasons, e.g. a dashboard).
- **Token lifecycle is borrowed, not owned.** This probe reads whatever
  access token is currently sitting in the credentials file; it does not
  refresh it. In practice this is fine on a fleetbroker node, because the
  persistent `claude rc` session in the same tmux `claude` session is always
  active and refreshes its own token through normal use - by the time this
  probe's token would be stale, the live session has almost always already
  refreshed it. If a tick does hit an expired token, `gather()`'s failure is
  caught by the runner's standard guarded-gather handling (one clean log
  line, no crash, tried again next tick) exactly like any other probe
  failure - it is not a special case.
- **Reading `~/.claude/.credentials.json` is a sensitive-file operation.**
  Treat `credentials_path` in probe_config as sensitive-adjacent
  configuration even though it's just a path, not a secret itself - the file
  it points to holds the same live token that authenticates this node's
  entire Remote Control identity.

## Recommendation for new deployments

Default to `anthropic_usage` for any new node - it has one fewer moving part
and one fewer non-`claude`-CLI dependency to set up. Use `ha_quota` only if
you specifically already have Home Assistant plus this HACS integration in
place and prefer that data path (e.g. you also want a dashboard, or you'd
rather not depend on an unofficial endpoint at all - HA's integration would
break the same way if the endpoint changed, but at least a HACS integration
update could absorb that for you, whereas this probe would need a matching
fleetbroker update).
