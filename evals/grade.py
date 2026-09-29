#!/usr/bin/env python3
"""Grade this submission against the client's own rubric, as an LLM eval.

    uv run python3 evals/grade.py                      # 3 models x 2 runs
    uv run python3 evals/grade.py --models gpt-4.1 --runs 1     # cheap
    uv run python3 evals/grade.py --out evals/results/grade.md

WHAT MAKES THIS AN EVAL AND NOT A COMPLIMENT
────────────────────────────────────────────
1. **The rubric is the client's words.** `evals/rubric.yaml` quotes S7 verbatim
   and is loaded, not summarised. A rubric written from memory grades the
   submission we think we were asked for.

2. **Mechanical checks are not sent to the model.** "Are the seven headings
   present" is a grep. Asking a judge is a worse grep that costs money and
   varies between runs. Code answers those; the model only weighs judgement.

3. **Every score must cite a quote from the submission.** A score with no
   evidence is an opinion, and the schema will not let one through.

4. **More than one draw, and more than one model.** One sample is not a
   measurement. Spread across runs is reported, and disagreement BETWEEN
   models is reported separately -- two models agreeing is weak evidence,
   two models disagreeing is strong evidence the criterion is ambiguous.

⚠️ THE CONFLICT OF INTEREST, STATED
An LLM is grading work an LLM wrote, on a rubric and prompt written by that
same LLM. Nothing here removes that. What it does is make the bias INSPECTABLE:
the rubric is verbatim, the prompt is in this file, the raw per-run scores are
saved, and the mechanical checks cannot be talked around. Read the number as
"a structured second opinion", never as a grade.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import litellm
import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from interfaceai.settings import get_settings
from interfaceai.vision_llm import PROFILES, _clamp_temperature, response_format

RUBRIC = yaml.safe_load((ROOT / "evals" / "rubric.yaml").read_text())


# --------------------------------------------------------------------------
# Mechanical checks. Code, not a model.
# --------------------------------------------------------------------------
def _report() -> str:
    return (ROOT / "REPORT.md").read_text()


def check_git_remote_is_public() -> tuple[bool, str]:
    try:
        url = subprocess.run(
            ["git", "-C", str(ROOT), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
    except Exception as exc:  # noqa: BLE001 -- a broken probe must report, not crash
        return False, f"could not read remote: {exc}"
    if not url:
        return False, "no origin remote"
    api = re.sub(r"^git@github\.com:|^https://github\.com/", "", url).removesuffix(".git")
    out = subprocess.run(
        ["gh", "api", f"repos/{api}", "--jq", ".visibility"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    ).stdout.strip()
    return out == "public", f"{api} is {out or 'unreachable'}"


def check_readme_has_setup() -> tuple[bool, str]:
    t = (ROOT / "README.md").read_text().lower()
    hits = [k for k in ("getting started", "requirements", ".secret", "docker compose") if k in t]
    return len(hits) >= 3, f"found {hits}"


def check_readme_demo_commands_resolve() -> tuple[bool, str]:
    """Every `interfaceai replay <path>` in the README must name a real file.

    This is the check that caught the headline demo pointing at
    `read_savings_balance.v2.approved.json`, which is a DRAFT -- so the one
    command a reviewer runs first errored on the artifact path.
    """
    text = (ROOT / "README.md").read_text()
    paths = re.findall(r"interfaceai replay\s+\\?\s*(\S+\.json)", text)
    missing = [p for p in paths if not (ROOT / p).exists()]
    return not missing and bool(paths), (
        f"{len(paths)} replay commands, missing: {missing}"
        if missing
        else f"all {len(paths)} replay commands resolve"
    )


def check_report_exists() -> tuple[bool, str]:
    p = ROOT / "REPORT.md"
    return p.exists(), str(p.relative_to(ROOT))


def check_report_has_seven_headings() -> tuple[bool, str]:
    want = [
        "Architecture",
        "Artifact schema",
        "Determinism & error handling",
        "Heterogeneity & multi-tenant",
        "Escalation & handoff",
        "Safety",
        "Cuts",
    ]
    found = re.findall(r"^## \d+\.\s*(.+)$", _report(), re.MULTILINE)
    missing = [w for w in want if not any(w.lower() in f.lower() for f in found)]
    return (
        not missing,
        f"{len(found)} numbered headings; missing {missing}" if missing else "all seven, in order",
    )


def check_report_word_count() -> tuple[bool, str]:
    n = len(_report().split())
    # ~1-3 pages. 600 words/page is generous for prose with tables and code.
    return n <= 1800, f"{n:,} words (~1-3 pages is roughly 600-1,800)"


def _committed_traces() -> list[Path]:
    """Only git-tracked traces count.

    ⚠️ This globbed the DISK first, and reported "448 committed" when 8 were --
    the other 440 are scratch runs `.gitignore` keeps out. A check that says
    "committed" has to ask git, or it is measuring the wrong thing and saying
    the right word.
    """
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "evidence/runs"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    ).stdout.splitlines()
    return sorted(ROOT / f for f in out if f.endswith("trace.jsonl"))


def check_evidence_has_discovery_and_replay() -> tuple[bool, str]:
    runs = _committed_traces()
    kinds = {"discovery": 0, "replay": 0}
    for t in runs:
        ev = {json.loads(line)["event"] for line in t.read_text().splitlines() if line.strip()}
        if {"artifact_drafted", "discovery_config"} & ev:
            kinds["discovery"] += 1
        elif "replay_started" in ev:
            kinds["replay"] += 1
    ok = kinds["discovery"] >= 1 and kinds["replay"] >= 1
    return ok, f"{kinds['discovery']} discovery, {kinds['replay']} replay, {len(runs)} committed"


def check_evidence_has_error_case() -> tuple[bool, str]:
    wanted = {"BusinessOutcome", "NeedsOperator", "Failed"}
    seen: set[str] = set()
    for t in _committed_traces():
        for line in t.read_text().splitlines():
            e = json.loads(line)
            if e.get("event") == "replay_finished":
                seen.add(e.get("outcome", ""))
    hit = wanted & seen
    return bool(hit), f"exceptional outcomes in committed evidence: {sorted(hit) or 'NONE'}"


CHECKS = {n.removeprefix("check_"): f for n, f in globals().items() if n.startswith("check_")}


def run_mechanical() -> list[dict]:
    out = []
    for d in RUBRIC["deliverables"]:
        fn = CHECKS.get(d["check"])
        try:
            ok, detail = fn() if fn else (False, f"no check named {d['check']}")
        except Exception as exc:  # noqa: BLE001 -- one bad check must not hide the rest
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        out.append({**d, "pass": ok, "detail": detail})
    return out


# --------------------------------------------------------------------------
# The judged half
# --------------------------------------------------------------------------
class CriterionScore(BaseModel):
    id: str
    score: int = Field(ge=0, le=4)
    evidence_quote: str = Field(
        description="A VERBATIM quote from the submission justifying this score."
    )
    justification: str
    strongest_objection: str = Field(description="The best argument that this score is too HIGH.")


class Grade(BaseModel):
    scores: list[CriterionScore]
    penalty: int = Field(ge=-2, le=0)
    penalty_reason: str
    overall: str


SYSTEM = """You are grading a take-home submission for a senior engineering role.

You are a SKEPTIC, not a reviewer trying to be encouraging. The submission was
written to be persuasive; your job is to find where the prose outruns the
evidence. Specifically:

- A claim in the write-up is worth nothing unless the code or the committed
  evidence backs it. If a section describes a mechanism, look for it.
- `evidence_quote` must be VERBATIM from the material provided. If you cannot
  find a quote supporting a score, the score is too high.
- `strongest_objection` must be a real argument against your own score. "None"
  is not acceptable for any score above 2.
- A submission that ADMITS a defect has told you about a defect. Do not reward
  the confession so generously that it outscores not having the defect, and do
  not double-punish it either.

Score 0-4 per the scale given. A 4 requires a MEASUREMENT, not a claim.
Reserve 4 for criteria where the submission shows a number, a counterexample,
or a rejected alternative."""


def build_payload() -> str:
    parts = [
        (
            "THE ASSIGNMENT -- section 7, the criteria you are applying",
            "\n".join(f"{c['name']}: {c['quote']}" for c in RUBRIC["criteria"]),
        ),
        ("REPORT.md -- the design write-up", _report()),
        ("README.md -- setup and demo path", (ROOT / "README.md").read_text()),
        (
            "evidence/README.md -- what the committed runs show",
            (ROOT / "evidence" / "README.md").read_text(),
        ),
        (
            "src/interfaceai/capability.py -- THE ARTIFACT SCHEMA (S7 calls this central)",
            (ROOT / "src" / "interfaceai" / "capability.py").read_text(),
        ),
        (
            "src/interfaceai/replay.py -- THE REPLAY CONTRACT (S7 calls this central)",
            (ROOT / "src" / "interfaceai" / "replay.py").read_text(),
        ),
    ]
    tr = _committed_traces()
    if tr:
        parts.append(
            ("A COMMITTED TRACE, verbatim -- " + tr[-1].parent.name, tr[-1].read_text()[:6000])
        )
    return "\n\n".join(f"{'=' * 70}\n### {t}\n{'=' * 70}\n{b}" for t, b in parts)


def build_prompt(payload: str) -> str:
    crit = "\n\n".join(
        f"id: {c['id']}\nname: {c['name']}\nweight: {c['weight']}\n"
        f"THE CLIENT'S WORDS: {c['quote']}\n"
        f"look for:\n" + "\n".join(f"  - {q}" for q in c["look_for"])
        for c in RUBRIC["criteria"]
    )
    scale = "\n".join(f"  {k} = {v}" for k, v in RUBRIC["meta"]["scale"].items())
    pen = RUBRIC["penalties"][0]
    return (
        f"SCALE\n{scale}\n\nCRITERIA\n{crit}\n\n"
        f"PENALTY (-2..0, 0 = nothing unrewarded was built)\n{pen['quote']}\n\n"
        f"Return one score per criterion id, in the order given.\n\n"
        f"THE SUBMISSION\n{payload}"
    )


# `claude` runs as a SEPARATE PROCESS with none of this session's context. That
# matters more than the model choice: an agent grading its own work inside the
# conversation where it argued for every decision is not a second opinion, it is
# the same opinion with a rubric stapled to it. A cold process has read only the
# submission.
CLI_GRADERS = {"claude-cli": ["claude", "-p", "--output-format", "json"]}


async def _run_cli(name: str, prompt: str) -> Grade:
    schema = json.dumps(Grade.model_json_schema(), indent=2)
    full = (
        f"{SYSTEM}\n\n{prompt}\n\n"
        "Reply with ONE json object and nothing else -- no prose, no markdown "
        f"fence. It must validate against this schema:\n{schema}"
    )
    proc = await asyncio.create_subprocess_exec(
        *CLI_GRADERS[name],
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd="/tmp",  # never the repo: the grader must read the payload, not browse
    )
    out, err = await proc.communicate(full.encode())
    if proc.returncode != 0:
        raise RuntimeError(f"{name} exited {proc.returncode}: {err.decode()[:200]}")
    text = out.decode()
    try:  # `--output-format json` wraps the reply in an envelope
        text = json.loads(text).get("result", text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise RuntimeError(f"{name}: no json in reply: {text[:200]}")
    return Grade.model_validate_json(m.group(0))


async def one_run(model_name: str, prompt: str) -> Grade:
    if model_name in CLI_GRADERS:
        return await _run_cli(model_name, prompt)
    cfg = PROFILES[model_name]
    key = get_settings().key_named(cfg["key_field"])
    if not key:
        raise RuntimeError(f"{model_name}: no key ({cfg['key_field']})")
    r = await litellm.acompletion(
        model=cfg["model"],
        api_base=cfg.get("api_base"),
        api_key=key,
        api_version=cfg.get("api_version"),
        max_tokens=int(cfg.get("max_tokens", 8000)),
        temperature=_clamp_temperature(cfg["model"], 0),
        response_format=response_format(Grade),
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
    )
    return Grade.model_validate_json(r.choices[0].message.content)


def render(mech: list[dict], grades: dict[str, list[Grade]], models: list[str]) -> str:
    by_id = {c["id"]: c for c in RUBRIC["criteria"]}
    L: list[str] = []
    A = L.append
    A("# Submission grade, against the client's own rubric\n")
    A(
        f"Generated `{datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}Z` by "
        f"`uv run python3 evals/grade.py`. Rubric: [`evals/rubric.yaml`](../rubric.yaml), "
        "quoting the assignment verbatim.\n"
    )
    A(
        "> ⚠️ **An LLM grading work an LLM wrote, on a prompt that same LLM chose.** "
        "The bias is not removed, only made inspectable: the rubric is verbatim, the "
        "mechanical checks below cannot be talked around, and every judged score had to "
        "cite a quote. Read it as a structured second opinion, not a grade.\n"
    )

    A("## Deliverables (§6) — checked in code, not judged\n")
    A("| | check | result |")
    A("|---|---|---|")
    for m in mech:
        A(f"| {'✅' if m['pass'] else '❌'} | `{m['id']}` | {m['detail']} |")
    fails = [m for m in mech if not m["pass"]]
    A(
        f"\n**{len(mech) - len(fails)}/{len(mech)} pass.**"
        + (f" Failing: {', '.join(m['id'] for m in fails)}." if fails else "")
    )

    A("\n## Judged criteria (§7)\n")
    hdr = " | ".join(models)
    A(f"| criterion | w | {hdr} | mean | spread |")
    A("|---|---|" + "---|" * len(models) + "---|---|")
    total_w = sum(c["weight"] for c in RUBRIC["criteria"])
    weighted = 0.0
    rows = []
    for cid, c in by_id.items():
        per_model = []
        allv: list[int] = []
        for mo in models:
            v = [s.score for g in grades.get(mo, []) for s in g.scores if s.id == cid]
            per_model.append(f"{statistics.mean(v):.1f}" if v else "—")
            allv += v
        mean = statistics.mean(allv) if allv else 0.0
        spread = f"{min(allv)}–{max(allv)}" if allv else "—"
        weighted += mean * c["weight"]
        rows.append((cid, allv))
        A(
            f"| **{c['name']}** | {c['weight']} | {' | '.join(per_model)} | **{mean:.2f}** | {spread} |"
        )
    pens = [g.penalty for gs in grades.values() for g in gs]
    pen = statistics.mean(pens) if pens else 0.0
    pct = (weighted / (4 * total_w)) * 100
    A(
        f"\n**Weighted: {pct:.0f}%** of the maximum "
        f"(weights are a linear ramp over §7's stated order — an interpretation, see the rubric). "
        f"Mean penalty {pen:+.1f}."
    )

    disputed = [(cid, v) for cid, v in rows if v and max(v) - min(v) >= 2]
    A("\n### Where the graders disagreed\n")
    if disputed:
        A(
            "Two models agreeing is weak evidence. Two disagreeing is strong evidence the "
            "criterion is genuinely ambiguous — these are the ones worth reading by hand.\n"
        )
        for cid, v in disputed:
            A(f"- **{by_id[cid]['name']}** — scores {sorted(v)}")
    else:
        A("No criterion split by 2 or more points.")

    A("\n## What each grader said\n")
    for mo in models:
        for i, g in enumerate(grades.get(mo, [])):
            A(f"<details><summary><b>{mo}</b> run {i + 1} — penalty {g.penalty:+d}</summary>\n")
            A(f"\n{g.overall}\n")
            for s in g.scores:
                A(f"\n**{by_id.get(s.id, {}).get('name', s.id)} — {s.score}/4**  ")
                A(f"> {s.evidence_quote.strip()[:400]}\n")
                A(f"{s.justification}  ")
                A(f"*Strongest objection:* {s.strongest_objection}")
            A(f"\n*Penalty:* {g.penalty_reason}\n")
            A("</details>\n")
    return "\n".join(L)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["gpt-4.1", "gpt-5.2-chat", "claude-cli"])
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    mech = run_mechanical()
    for m in mech:
        print(f"  {'PASS' if m['pass'] else 'FAIL'}  {m['id']:<26} {m['detail']}")

    prompt = build_prompt(build_payload())
    print(f"\npayload ~{len(prompt) // 4:,} tokens; {len(args.models)} models x {args.runs} runs")

    grades: dict[str, list[Grade]] = {}
    for mo in args.models:
        res = await asyncio.gather(
            *(one_run(mo, prompt) for _ in range(args.runs)), return_exceptions=True
        )
        ok = [r for r in res if isinstance(r, Grade)]
        for r in res:
            if not isinstance(r, Grade):
                print(f"  {mo}: {type(r).__name__}: {str(r)[:100]}")
        grades[mo] = ok
        print(f"  {mo}: {len(ok)}/{args.runs} ok")

    models = [m for m in args.models if grades.get(m)]
    if not models:
        print("no grader returned a result")
        return 1
    md = render(mech, grades, models)
    out = args.out or ROOT / "evals" / "results" / (
        f"grade-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    print(f"\nwrote {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
