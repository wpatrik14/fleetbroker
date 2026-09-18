# Shared backlog with fairness: `gh_backlog`

## What problem this solves

Once more than one site shares an idea of "spare quota, go do something
useful," the next question is *what*, and whether one site can end up always
winning. `fleetbroker.probes.gh_backlog` turns a GitHub Issues repo into the
shared backlog: estimation, priority, and reservation are all plain labels,
and the claim itself is the GitHub assignee/label state — no new database, no
cross-node state sync (which v1 deliberately excludes; see the plan's
"explicitly out of scope" section). GitHub already is the one shared,
independently-readable source of truth both sites poll.

## Label convention

- `priority:P1` / `P2` / `P3` — matches an existing project-local
  `AUTONOMOUS_BACKLOG.md` convention this project's operator already used
  across a couple of other repos before this probe existed. P1 sorts first;
  unlabeled issues sort last but are still eligible.
- `size:S` / `M` / `L` — same effort-tag convention as those files. Shown in
  the relay message so a tight-daily-cap window can be matched to something
  that actually fits, same reasoning as the quota probe's own daily-cap
  guidance.
- `site:shared` — open to any known site. `site:<name>` — reserved for one
  site, invisible as a candidate to every other site. No label at all behaves
  like `site:shared`.
- `claimed-by:<name>` — the lock. Added by the **receiving Claude session**
  at claim time (`gh issue edit <n> -R <repo> --add-assignee @me --add-label
  claimed-by:<name>`), never by the probe itself - `gather()` only reads. This
  keeps the same separation the rest of the project uses: the cron-driven
  probe only ever notifies; the persistent session with full context decides
  and acts.

## Fairness

`prepare_state()` counts, per known site, how many issues currently carry
`claimed-by:<site>` — open ones count unconditionally (still in progress),
closed ones only if closed within `fairness_window_days` (default 7). If this
site's count is already higher than the *lowest* count among the other known
sites, `decide()` holds back even when eligible candidates exist, so a quieter
peer gets a turn instead of one site permanently outpacing another. With only
one known site configured, the check is a no-op.

This is intentionally simple (compare counts, not weighted effort-points) -
matches the project's existing "no special-casing" preference from the daily-
cap logic. A size-weighted fairness measure is a natural refinement if plain
issue counts turn out to be too coarse in practice, not something to
pre-build speculatively.

## What this does not do

- Does not create labels or the repo itself - point `probe_config.repo` at an
  existing repo and create the labels above once, by hand or with a short
  `gh label create` script.
- Does not resolve a race where two sites claim the same issue within the
  same poll interval - GitHub's assignee API is last-write-wins, not a lock.
  In practice this is a low-frequency, human/agent-mediated action (one claim
  attempt per green light, hours apart), so the residual risk is a duplicate
  claim needing a manual "oh, someone already has this" resolution, not a
  correctness-critical failure.
- Does not pick *which* repo to use - reusing an existing repo, or standing
  up a dedicated backlog repo, is a deliberate choice left to whoever wires
  `probe_config.repo` for real; this probe is repo-agnostic.
