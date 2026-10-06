#!/usr/bin/env python3
"""Draw the DISCOVERY loop three ways, so the choice is made on the output.

    uv run python3 scripts/diagram_variants.py

Three renderers, one flow:

  1  hand-written mermaid          what README uses today
  2  graph-builder-spec            a DECLARED spec -> diagram() + check_*()
  3  pydantic-graph                a BUILT Graph -> mermaid_code()

⚠️ They are not interchangeable, and the difference is what to decide on:

  hand         draws anything, including things the code does not do. Zero
               dependencies, zero guarantees. It is a claim.
  workbench    draws a DECLARATION. Needs no implementation, so an unbuilt or
               partly-built design still renders -- and the same declaration is
               what `check_reachable`, `check_names` and friends read, so the
               picture and the lint cannot disagree.
  pydantic     draws a BUILT graph. The strongest guarantee of the three -- it
               cannot draw a node that does not exist -- and the highest cost,
               because it means restructuring replay into Graph nodes rather
               than a `for` loop over steps.
"""


# forward refs inside a function body raises NameError.

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# --------------------------------------------------------------------------
# 1. by hand -- lifted verbatim from README
# --------------------------------------------------------------------------
BY_HAND = """flowchart TD
  D1[observe: screenshot] --> D2[inventory controls<br/>read clean, locate gridded]
  D2 --> D3{next move?}
  D3 -->|act| D4[validate -> use_control] --> D1
  D3 -->|finish| D5[draft a capability]
  D3 -->|stuck| D6[PassToOperator]"""


# --------------------------------------------------------------------------
# 2. graph-builder-spec -- the flow as DATA
# --------------------------------------------------------------------------
def by_workbench() -> tuple[str, list[str]]:
    from graph_builder_spec import (
        END,
        START,
        DecisionSpec,
        EdgeSpec,
        NodeSpec,
        StepSpec,
        VariableSpec,
        check_names,
        check_reachable,
        check_variables,
        diagram,
    )

    goal = VariableSpec("goal", str)
    frame = VariableSpec("frame", bytes)
    controls = VariableSpec("controls", tuple)
    move = VariableSpec("move", str)
    artifact = VariableSpec("artifact", str)

    # ⚠️ `observe` takes EITHER the goal (first pass) or the frame the last
    # action produced (every pass after). check_variables caught this: the
    # loop-back edge delivered `frame` to a node declaring only `goal`.
    observe = StepSpec("observe", inputs=(goal, frame), outputs=(frame,))
    inventory = StepSpec("inventory", inputs=(frame,), outputs=(controls,))
    decide = DecisionSpec(
        "next_move", inputs=(controls,), outputs=(move,), note="the ONLY model decision"
    )
    act = StepSpec("act", inputs=(move,), outputs=(frame,))
    draft = StepSpec("draft_capability", inputs=(controls, move), outputs=(artifact,))
    escalate = StepSpec("pass_to_operator", inputs=(move,), outputs=(artifact,))

    # ⚠️ `tuple[NodeSpec, ...]` AND NOT `tuple[StepSpec, ...]` -- `decide` is a
    # `DecisionSpec`. This is the trap in graph-builder-spec's 0.2 migration
    # guide: the blanket sed rewrites every `NodeSpec`, including annotations
    # that legitimately mean the union of every declared box.
    #
    # There was no annotation here before, so the sed would have been harmless
    # BY LUCK. Stating it makes the union deliberate rather than accidental,
    # and it is what the three checks below actually receive.
    nodes: tuple[NodeSpec, ...] = (observe, inventory, decide, act, draft, escalate)
    edges = (
        EdgeSpec(source=START, target=observe, carries=goal),
        EdgeSpec(source=observe, target=inventory, carries=frame),
        EdgeSpec(source=inventory, target=decide, carries=controls),
        EdgeSpec(source=decide, target=act, carries=move),
        EdgeSpec(source=act, target=observe, carries=frame),  # THE CYCLE
        EdgeSpec(source=decide, target=draft, carries=move),
        EdgeSpec(source=decide, target=escalate, carries=move),
        EdgeSpec(source=draft, target=END, carries=artifact),
        EdgeSpec(source=escalate, target=END, carries=artifact),
    )
    findings: list[str] = []
    for name, result in (
        ("check_names", check_names(nodes)),
        ("check_reachable", check_reachable(nodes, edges)),
        ("check_variables", check_variables(nodes, edges)),
    ):
        findings.append(f"  {name}: {'; '.join(result) if result else 'ok'}")
    return diagram(nodes, edges, title="discovery (declared)"), findings


# --------------------------------------------------------------------------
# 3. pydantic-graph -- a BUILT graph
# --------------------------------------------------------------------------
def by_pydantic_graph() -> str:
    """pydantic-graph 2.x builds from steps, not a bare `Graph(nodes=...)`.

    ⚠️ The 1.x shape -- subclass `BaseNode`, pass the classes to `Graph` -- is
    what most examples online still show and it raises `TypeError: missing 9
    required positional arguments` here. Measured against 2.51.0.
    """
    from pydantic_graph import GraphBuilder, StepContext

    g = GraphBuilder(state_type=None, input_type=str, output_type=str)

    @g.step
    async def observe(ctx: StepContext[None, None, str]) -> str:
        return ctx.inputs

    @g.step
    async def inventory(ctx: StepContext[None, None, str]) -> str:
        return ctx.inputs

    @g.step
    async def act(ctx: StepContext[None, None, str]) -> str:
        return ctx.inputs

    @g.step
    async def draft_capability(ctx: StepContext[None, None, str]) -> str:
        return ctx.inputs

    g.add(
        g.edge_from(g.start_node).to(observe),
        g.edge_from(observe).to(inventory),
        g.edge_from(inventory).to(act),
        g.edge_from(act).to(draft_capability),
        g.edge_from(draft_capability).to(g.end_node),
    )
    return g.build().render()


def main() -> int:
    print("=" * 72, "\n1. BY HAND (what README ships today)\n", "=" * 72, sep="")
    print(BY_HAND)

    print(
        "\n" + "=" * 72, "\n2. graph-builder-spec -- declared, not implemented\n", "=" * 72, sep=""
    )
    try:
        mmd, findings = by_workbench()
        print(mmd)
        print("\n  and the SAME declaration is what the checks read:")
        print("\n".join(findings))
    except Exception as exc:  # noqa: BLE001
        print(f"  unavailable: {type(exc).__name__}: {exc}")

    print("\n" + "=" * 72, "\n3. pydantic-graph -- built, then rendered\n", "=" * 72, sep="")
    try:
        print(by_pydantic_graph())
    except Exception as exc:  # noqa: BLE001
        print(f"  unavailable: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
