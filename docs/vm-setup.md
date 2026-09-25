# Setting up on a fresh machine

Written for a remote VM running Claude Code, but it is the same on any new
machine. Everything except the two API keys comes from the repo.

## What the VM needs

| | Why | Check |
|---|---|---|
| **git** | clone the repo | `git --version` |
| **Docker + `docker compose`** | ParaBank runs in a container | `docker compose version` |
| **uv** | the project uses it, not pip | `uv --version` |
| Python 3.13 | pinned in `.python-version` | uv installs it |
| **~2 GB disk** | ParaBank image ~250 MB, Chromium ~100 MB, venv ~1 GB (opencv, litellm) | |
| x86_64 **or** arm64 | `parasoft/parabank` is multi-arch, native on both | `uname -m` |

Headless works for everything except the human-handoff demo, which needs
`page.pause()` and therefore a display. On a headless VM, run discovery and
replay there and demo the handoff locally.

## 1. Clone and install

```bash
git clone git@github.com:borisdev/ai_computer_use.git
cd ai_computer_use

uv sync                        # creates .venv, fetches Python 3.13, installs deps
uv run playwright install chromium     # ~100 MB browser download
```

`uv sync` alone is not enough — Playwright ships the library but downloads the
browser separately, and nothing warns you until a run fails.

## 2. Secrets

Two Azure OpenAI keys, in a gitignored `.secret` at the repo root:

```
VISION_API_KEY=<the API_KEY for openai-rg-nobsmed>
VISION_API_KEY_EASTUS2=<the EASTUS2_API_KEY for boris-m3ndov9n-eastus2>
```

Both exist in `~/workspace/nobsmed-v2/.secret` on the laptop, under their
original names. Only `VISION_API_KEY` is needed for the default profile
(`gpt-4.1`); the eastus2 one is for `gpt-5.2-chat`.

**Getting them onto the VM.** In order of preference:

1. **Issue separate keys for the VM** from the Azure portal. Best: revocable
   independently, and a leak on the VM does not compromise the laptop's.
2. **`scp` the file** directly, laptop to VM:
   ```bash
   scp .secret user@vm:~/ai_computer_use/.secret
   ```
3. **Paste them into an editor over SSH.** Fine, but they land in shell history
   if you use `echo`.

Never: commit them, put them in `.env` (which IS committed), or send them
through a chat or ticket. `.secret` is in `.gitignore`; keep it that way.

Verify without printing anything:

```bash
uv run python -c "
from interfaceai.settings import get_settings
s = get_settings()
print('vision key loaded:', bool(s.key_named('vision_api_key')))
print('eastus2 loaded   :', bool(s.key_named('vision_api_key_eastus2')))
print('profile          :', s.vision_profile)
"
```

## 3. Start the target

```bash
docker compose up -d --wait          # pulls ~250 MB on first run
uv run interfaceai env reset         # seed the database AND verify it took
uv run interfaceai env status        # expect: ready
```

**Both commands are required.** ParaBank boots with no database schema and
serves HTTP 200 regardless — `docker compose ps` will say `healthy` while every
lookup fails. See [parabank.md §4](parabank.md#4--it-boots-with-no-database-schema).

Ports bound on the host: **8080** (web), 61616 (JMS), 9001 (HSQLDB), and
8081/61617/9002 for tenant B under the `tenant-b` profile. If any are taken,
override them in `.env` rather than editing `docker-compose.yml`.

## 4. Verify the whole stack

```bash
uv run pytest -q                              # 49 tests, includes live ParaBank
uv run python -m doctest src/interfaceai/screenshot2controls.py
uv run ruff check .
```

`pytest` is the real check: 4 of those tests hit the running container, so a
green run proves Docker, seeding, the venv and Playwright are all working.

To confirm the model path end to end (costs a few cents):

```bash
uv run python -c "
import asyncio
from pydantic import BaseModel
from interfaceai.vision_llm import call_vision_llm
class R(BaseModel):
    heading: str
print(asyncio.run(call_vision_llm(
    prompt='What is the main heading?',
    image_png=open('evidence/screens/01-home-login.png','rb').read(),
    response_model=R)))
"
```

Expect `heading='Welcome to ParaBank'`.

## 5. Teardown

```bash
docker compose --profile tenant-b down
```

Use the profile flag even if you never started tenant B — plain `down` ignores
profiled services and can leave an orphan holding the network. The database
lives in the container, so this is a full reset and step 3 is required again.

## Notes for a headless VM

- **Playwright needs system libraries** beyond the browser binary on a bare
  Linux image. If Chromium fails to launch, `uv run playwright install-deps
  chromium` (needs sudo) installs them.
- **`page.pause()` requires a display.** The human-handoff path
  ([issue 0004](issues/0004-sync-playwright-async.md) context) cannot be
  demonstrated headless. Everything else runs fine.
- **Docker-in-Docker**: if the VM is itself a container, ParaBank needs a real
  Docker daemon. Check `docker run --rm hello-world` before anything else.
