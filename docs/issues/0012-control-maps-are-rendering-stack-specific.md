# 0012 · A control map is specific to the stack that rendered it, and never said so

**Status:** open · **Found:** 2026-10-07, by a reviewer running the README on a
machine that was not the one it was written on.

## What happened

First command of the demo path, on an M1 MacBook Air (macOS Tahoe 26.2),
against a repo whose `control_maps/` were built on Linux:

```
needs a human at step 0 on index
  why  could not locate 'username_textbox' on the live screen:
       not_found (best score 0.6889 is below threshold 0.95)
```

`username_textbox` is the first control of the first screen. Nothing was
misconfigured and nothing had drifted in the application — the same commit,
the same ParaBank image, the same viewport.

## Why

A visual locator is a **template PNG**: a crop of the control as it looked when
discovery recorded it, matched against the live screenshot with
`cv2.TM_CCOEFF_NORMED` at threshold `0.95`. Those crops were rasterised by
**Linux** Chromium. macOS Chromium hints and antialiases text differently, so
the same control is literally different pixels.

0.6889 is not a near miss. For scale, from this repo's own measurements:

```
cross-tenant, same stack      1.0000     both ParaBank images, unbranded
the tightest case on record   0.9998     issue 0002, "one antialiasing change from failing"
reskinned tenant B            8/25 matched
macOS vs Linux                0.6889     THIS — below the floor of everything above
```

**The system behaved correctly.** It refused to click a control it was 69%
confident about and escalated to a human, rather than clicking the wrong
element in a banking flow. The guardrail fired on a genuine, unstaged drift —
which is the §3 "UI drift" question answered with a measurement rather than a
paragraph.

## The actual defect: the dependency was never recorded

`VisualLocator.reference_size` pinned the **viewport** (1280×900). Nothing
pinned the **rasteriser**. So the failure arrives as a bare number, and a
reader has no way to learn that the templates came from another machine.

Fixed in the schema, 2026-10-07 — `ScreenOutput.captured_on`:

```json
{"platform": "linux", "browser": "chromium 153.0.8010.12",
 "viewport": {"width": 1280, "height": 900}, "device_scale_factor": 1.0}
```

Read off the live browser, never assumed, so it cannot drift from what
actually rendered. `environment_mismatch()` turns the mystery into a sentence:

```
these templates were captured on a different rendering stack
(platform linux -> darwin; browser chromium 153.0.8010.12 -> chromium 141.0.7390.37)
```

⚠️ **This does not make a map portable.** It makes the failure diagnosable,
which is the honest limit of a recorded field. The field is optional and
defaults to `None` so every map already on disk reads as *"nobody recorded
it"* — never as *"it matches yours"*. A missing input must not read as a pass.

## Reproducing it

Deterministic, and it needs no Mac — capture on one stack, match on another:

```bash
docker compose up -d --wait && uv run banking-jobs env reset

# 1. maps from THIS machine's browser
uv run banking-jobs discover --maps /tmp/maps_a \
  --goal "read the balance of account 13344" --name probe \
  --param account_id=account_id=13344 \
  --secret parabank_username=username --secret parabank_demo_password=password

# 2. match them from a different one — any container whose Chromium differs
docker run --rm -v "$PWD:/w" -w /w --network host \
  mcr.microsoft.com/playwright/python:latest \
  bash -c "pip install -q uv && uv run banking-jobs replay probe --maps /tmp/maps_a --param account_id=13344"
```

## Options, and why only one of them is being taken

| | |
|---|---|
| **Pin the stack — run the agent in a container** | Chosen. Every host drives the same Linux Chromium the templates came from, so the host leaves the path entirely and a reviewer cannot hit 0.6889. Needs no schema change and no second map. |
| Record the environment | **Done** — above. Does not fix anything; makes the failure legible, and is what a future developer needs to diagnose the next one. |
| One map per environment, keyed like a tenant | **Not built.** `MapKey` would grow a dimension and the store would hold `linux/…` and `darwin/…` side by side. It is the right shape *if* multiple hosts must be supported directly — but pinning the stack makes it unnecessary, and building it now is an abstraction ahead of its caller (`project.md`). Recorded so the option is not re-derived. |
| Lower the threshold | **No.** 0.6889 against 0.95 is not a tuning problem, and a threshold low enough to admit it would admit the wrong control. Issue 0009 is what that costs. |
| Rebuild maps per machine (`--maps`) | The workaround available today: point `discover` at an empty store and it builds native templates. Costs ~20–25 model calls for the first screen, and the committed artifacts still will not replay against someone else's maps. |

## What this changes about the submission's claims

REPORT §4 argues cross-tenant portability from two ParaBank images matching at
`1.0000` and a reskin where 8/25 survived. Both hold the rendering stack
constant, so neither tests this axis at all. **The strongest portability
evidence in the repo is now this failure**, because it is the only measurement
of the locator strategy taken under conditions that could — and did — defeat it.
