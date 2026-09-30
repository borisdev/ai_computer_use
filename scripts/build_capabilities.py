#!/usr/bin/env python3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B = "https://github.com/borisdev/ai_computer_use/blob/main"
T = "https://github.com/borisdev/ai_computer_use/tree/main"

CAPS = [
    {
        "origin": "✍️ hand-authored<br/><sub>predates panel discovery</sub>",
        "name": "read_savings_balance",
        "ver": "v3",
        "anchor": "read_savings_balance-v3",
        "art": "read_savings_balance.v3.approved.json",
        "sig": "(account_id) → balance, account_type",
        "run": "--param account_id=13344",
        "desc": "Look up an account by id and read its balance. The brief's own worked example.",
        "a": ("✅", "`Success` · 12 steps", "20260929T071443Z"),
        "b": ("✅", "`Success` · 12 steps", "20260929T192201Z"),
        "demo": [
            (
                "Panel extraction",
                "one model call for the whole table; the row is picked **in code**",
            ),
            (
                "A checkpoint with teeth",
                "asserts `account_type = SAVINGS`, so CLEAN state fails instead of returning a stranger's balance",
            ),
            ("Business outcome", "account 99999 exits **0** — a fair negative answer, not a crash"),
        ],
        "extra": [("`BusinessOutcome` — account 99999", "20260929T071501Z")],
    },
    {
        "origin": "✍️ hand-authored",
        "name": "log_in",
        "ver": "v2",
        "anchor": "log_in-v2",
        "art": "log_in.v2.approved.json",
        "sig": "() → nothing",
        "run": "",
        "desc": "Authenticate and reach the authenticated nav.",
        "a": ("✅", "`Success` · 4 steps", "20260929T192254Z"),
        "b": ("✅", "`Success` · 4 steps", "20260929T192301Z"),
        "demo": [
            (
                "Compositional capabilities",
                "invoked by three others in the **same browser session**",
            ),
            (
                "Pinned versions",
                "a newer `log_in` is a validation error, never a silent substitution",
            ),
            (
                "Postconditions",
                "`establishes` is what recovery reads to know what restores a session",
            ),
        ],
        "extra": [],
    },
    {
        "origin": "🤖 <b>discovered</b><br/><sub>by a real LLM run</sub>",
        "name": "log_in_discovered",
        "ver": "v1",
        "anchor": "log_in_discovered-v1",
        "art": "log_in_discovered.v1.approved.json",
        "sig": "() → account_id",
        "run": "",
        "desc": "Authenticate and read back the account id. **The only artifact an LLM wrote.**",
        "a": ("✅", "`Success` · 5 steps", "20260929T192220Z"),
        "b": ("✅", "`Success` · 5 steps", "20260929T192231Z"),
        "demo": [
            ("Discovery works", "a real LLM run — 3 steps, 4 model calls, 24s"),
            (
                "Discovered beats authored",
                "**0 faults on first emission**; the first hand-written drafts had 3 and 8, naming a screen that does not exist",
            ),
            ("Human handoff", "`requested → human_acted → returned`, on the same live session"),
        ],
        "extra": [
            ("the discovery run that produced it", "20260926T022551Z"),
            ("a full handoff", "20260929T051949Z"),
        ],
    },
    {
        "origin": "🤖 <b>discovered</b><br/><sub>panel and all</sub>",
        "name": "discovered_balance",
        "ver": "v1",
        "anchor": "discovered_balance-v1",
        "art": "discovered_balance.v1.approved.json",
        "sig": "(account_id) → account_id, balance",
        "run": "--param account_id=13344",
        "desc": "Read one account's balance out of the accounts table. **Discovered including its `TABLE_CONTROL_PANEL`** — the gap #6 was open on.",
        "a": ("✅", "`Success` · 6 steps", "20260930T035056Z"),
        "b": ("✅", "`Success` · 6 steps", "20260930T035110Z"),
        "demo": [
            (
                "A discovered panel",
                "geometry measured the table — **11 rows, 28px pitch, autocorrelation 0.899** — and no pixel was asked of a model",
            ),
            (
                "The row by arithmetic",
                "`row_key=account_id`, `field=balance`; the whole table is read in one call and the row picked **in code**",
            ),
            (
                "Cross-tenant, discovered",
                "the heading it anchored on matches a **different build** of ParaBank, unchanged",
            ),
        ],
        "extra": [("the discovery run that produced it", "20260929T232850Z")],
    },
    {
        "origin": "🤖 <b>discovered</b><br/><sub>the brief's own example</sub>",
        "name": "discovered_account_type",
        "ver": "v1",
        "anchor": "discovered_account_type-v1",
        "art": "discovered_account_type.v1.approved.json",
        "sig": "(account_id) → account_id, account_type",
        "run": "--param account_id=13344",
        "desc": "Open an account from the table and read its TYPE off the detail page. **The same shape as `read_savings_balance`, discovered** — two panels and a drilldown between them.",
        "a": ("✅", "`Success` · 7 steps", "20260930T035124Z"),
        "b": ("✅", "`Success` · 7 steps", "20260930T035146Z"),
        "demo": [
            (
                "A drilldown, discovered",
                "`click` on a panel with `row_key=account_id` — the row's position comes from the panel read and the measured pitch, never from pointing at it",
            ),
            (
                "Two discovered panels",
                "a TABLE on the overview and a LABEL/VALUE block on the detail page; the second shape was invisible to the read pass until it was named",
            ),
            (
                "A checkpoint with teeth, derived",
                "`account_type == SAVINGS` was inferred from the run, and `interfaceai env break` makes it fail with **observed CHECKING**",
            ),
        ],
        "extra": [
            ("the discovery run that produced it", "20260930T033307Z"),
            ("the checkpoint firing on a changed record", "20260930T035024Z"),
        ],
    },
    {
        "origin": "✍️ hand-authored<br/><sub>predates panel discovery</sub>",
        "name": "request_loan",
        "ver": "v2",
        "anchor": "request_loan-v2",
        "art": "request_loan.v2.approved.json",
        "sig": "(amount, down_payment) → nothing",
        "run": "--param amount=25000 --param down_payment=5000 --confirm-risky",
        "desc": "Apply for a loan of a given amount with a given down payment.",
        "a": ("⚠️", "`NeedsOperator` · over the $1,000 threshold", "20260929T071538Z"),
        "b": ("⛔", "`Failed` · tenant does not permit it", "20260929T192346Z"),
        "demo": [
            (
                "Value-dependent risk",
                "$25,000 stops, $500 does not, and `--confirm-risky` cannot buy past it",
            ),
            (
                "Irreversible means observed",
                "a schema rule: a `risky` step must be followed by a look",
            ),
            ("Tenant permissions", "refused **before a browser opens**"),
        ],
        "extra": [],
    },
    {
        "origin": "✍️ hand-authored<br/><sub>predates panel discovery</sub>",
        "name": "session_loss_probe",
        "ver": "v1",
        "anchor": "session_loss_probe-v1",
        "art": "session_loss_probe.v1.approved.json",
        "sig": "(account_id) → found_account_id",
        "run": "--param account_id=13344",
        "desc": "Read an account, destroy its own session mid-flow, and carry on.",
        "a": ("✅", "`Success` + `recovered`", "20260929T071516Z"),
        "b": ("⛔", "`Failed` · tenant does not permit it", "20260929T192329Z"),
        "demo": [
            (
                "Bounded recovery",
                "re-establishes a lost session **once per condition**, never in a loop",
            ),
            (
                "No `Recoverable` type",
                "a recovered condition is not a terminal state; `Success.recovered` names it",
            ),
        ],
        "extra": [],
    },
]

L = [
    """# Capabilities

Five capabilities, what each demonstrates, and a committed trace behind every
claim.

<table>
<tr><th width="24%">capability</th><th width="11%">origin</th><th width="16%">artifacts</th><th width="16%">tenants</th><th>demonstrates</th></tr>"""
]


def md(text: str) -> str:
    """Just enough inline markdown for a table cell GitHub renders as HTML."""
    import re

    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return text


for c in CAPS:
    demo = "".join(f"<li><b>{t}</b> — {md(d)}</li>" for t, d in c["demo"])
    arts = (
        f'<li><a href="{B}/artifacts/{c["art"]}">exported workflow</a></li>'
        f'<li><a href="{T}/evidence/runs/{c["a"][2]}">evidence · A</a></li>'
        f'<li><a href="{T}/evidence/runs/{c["b"][2]}">evidence · B</a></li>'
        f'<li><a href="#{c["anchor"]}">mermaid diagram</a></li>'
    )
    tenants = (
        f"<li>{c['a'][0]} <b>A</b> baseline<br/><sub>{md(c['a'][1])}</sub></li>"
        f"<li>{c['b'][0]} <b>B</b> feature<br/><sub>{md(c['b'][1])}</sub></li>"
    )
    L.append(
        f"<tr><td><code>{c['name']}</code> <b>{c['ver']}</b>"
        f"<br/><sub><code>{c['sig']}</code></sub>"
        f"<p>{md(c['desc'])}</p></td>"
        f"<td>{c['origin']}</td>"
        f"<td><ul>{arts}</ul></td>"
        f"<td><ul>{tenants}</ul></td>"
        f"<td><ul>{demo}</ul></td></tr>"
    )

L.append("""</table>

✅ ran · ⚠️ stopped for a policy reason · ⛔ refused before a browser opened.

⚠️ **Why these, and no more.** The brief (§2) asks for one goal driven end to
end — *"look up member 12345 and read their current savings balance"* — and then
for the SYSTEM around it. Each one here earns an outcome type or a guardrail an
**observed instance**; none was added because a bank needs the feature. §7 says
feature breadth is not rewarded.

⚠️ Two of them answer the SAME goal, and that is the point of the pair:
`read_savings_balance` was written by a person and `discovered_balance` was
discovered, panel included. Compare them rather than counting them — the
authored one checks `account_type` on the detail page, which discovery does not
reach, and the discovered one names nothing it did not see.

---
""")

for c in CAPS:
    extra = ""
    if c["extra"]:
        extra = (
            "\n**Also:** "
            + " · ".join(f"[{label}]({T}/evidence/runs/{d})" for label, d in c["extra"])
            + "\n"
        )
    diagram = subprocess.run(
        ["uv", "run", "interfaceai", "diagram", c["name"]],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    ).stdout
    diagram = "\n".join(l for l in diagram.splitlines() if "litellm" not in l.lower())
    diagram = diagram.replace("```mermaid", "").replace("```", "").strip()
    L.append(f"""## `{c["name"]}` {c["ver"]}

{c["desc"]}  `{c["sig"]}`

| tenant | outcome | evidence |
|---|---|---|
| `baseline` | {c["a"][0]} {c["a"][1]} | [trace]({T}/evidence/runs/{c["a"][2]}) |
| `feature` | {c["b"][0]} {c["b"][1]} | [trace]({T}/evidence/runs/{c["b"][2]}) |

**Run it:**

```bash
uv run interfaceai replay -c {c["name"]} {c["run"]}
```

[**exported workflow**]({B}/artifacts/{c["art"]}) — approved, version-pinned.
{extra}
```mermaid
{diagram}
```
""")

# ⚠️ THE TAIL IS PART OF THE GENERATED FILE. Appending prose to CAPABILITIES.md
# by hand loses it on the next rebuild -- which happened once, silently.
L.append((ROOT / "docs" / "_parts" / "capabilities-tail.md").read_text())
Path(ROOT / "CAPABILITIES.md").write_text("\n".join(L))
print("wrote CAPABILITIES.md")
