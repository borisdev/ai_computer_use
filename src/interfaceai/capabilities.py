"""The authored capabilities, and the registry that serves them.

⚠️ **These are hand-authored, not discovered.** The discovery loop (S3.1) does
not exist yet, so these are the TARGET SHAPE it must emit rather than evidence
that it can. They are here because the step executor (S3.3) needs something
real to execute, and because an artifact schema with no instance is a schema
nobody has tried to write anything in.

Both are `draft`. That is not a placeholder -- nothing has reviewed a real run
of either, and `draft` is exactly what that state is called. `interfaceai
capability approve` is the human action that changes it.

⛔ **Neither of these can replay, and `interfaceai capability check` says so.**
Measured 2026-09-26 against the control maps a real discovery run produced:

    log_in                  hand-authored    3 faults
    read_savings_balance    hand-authored    8 faults
    log_in_discovered       DISCOVERED       0 faults

Every fault is a control name invented here that no inventory emits --
`global_nav` (a pseudo-screen with no producer), `accounts_overview_heading` and
`*_value` (static text, which the coarse prompt is told to ignore --
`docs/issues/0010`), and `account_link` (discovery records `13344_link` --
`docs/issues/0007`).

**That contrast is the argument for discovery, not a bug to patch.** A
hand-written artifact can name anything; a discovered one can only name what it
recorded. These stay as the target SHAPE, and the check staying red on them is
correct.

`read_savings_balance` is the assignment's own worked example and is
self-checking: account 13344 is SAVINGS $1,231.10 after a seed, and CHECKING
$5,022.93 after ParaBank's CLEAN. So its checkpoint has a known-correct answer
and a known-wrong one, from the app's own admin page.
"""

from __future__ import annotations

from interfaceai.capability import (
    Capability,
    Checkpoint,
    ControlRef,
    LiteralValue,
    OutputSpec,
    ParamSpec,
    ParamValue,
    Precondition,
    SecretValue,
    Step,
    StepVerb,
    Target,
    validate_capability,
)
from interfaceai.surface import Viewport
from interfaceai.vocabulary import VOCABULARY_VERSION

_VIEWPORT = Viewport()

TARGET = Target(app="parabank", tenant="baseline", base_url="http://localhost:8080/parabank")

# ParaBank's global nav (Open New Account, Accounts Overview, Transfer Funds,
# Bill Pay, Find Transactions, Update Contact Info, Request Loan, Log Out) is
# rendered on EVERY authenticated screen at the same place. Giving it its own
# screen name means its locators are recorded once instead of once per screen,
# and a precondition can ask "is Log Out visible" without naming where we are.
NAV = "global_nav"


LOG_IN = Capability(
    name="log_in",
    version=1,
    goal="log in to the bank as the operator's seeded customer",
    vocabulary_version=VOCABULARY_VERSION,
    target=TARGET,
    viewport_width=_VIEWPORT.width,
    viewport_height=_VIEWPORT.height,
    # No params. Credentials are NOT caller arguments -- they are names the
    # runtime resolves from a secret provider, so nothing about them can reach
    # this file. A real deployment parameterises WHICH key is resolved; that is
    # a runtime binding, not an artifact field, and it is not built.
    params=(),
    returns=(OutputSpec(name="customer_first_name", slot="first_name"),),
    requires=(
        Precondition(
            name="not_already_authenticated",
            control=ControlRef(screen=NAV, control_id="log_out_link"),
            must="absent",
            why=(
                "Logging in on top of a live session lands on a different screen "
                "than the one every step below was recorded against."
            ),
        ),
    ),
    steps=(
        Step(
            verb=StepVerb.ENTER,
            control=ControlRef(screen="index", control_id="username_textbox"),
            slot="username",
            value=SecretValue(input_ref="parabank_username"),
            note="Sensitive slot: the artifact carries the KEY, never the value.",
        ),
        Step(
            verb=StepVerb.ENTER,
            control=ControlRef(screen="index", control_id="password_textbox"),
            slot="password",
            value=SecretValue(input_ref="parabank_demo_password"),
            note="Same. `use_control` logs value_length and never the value.",
        ),
        Step(
            verb=StepVerb.CLICK,
            control=ControlRef(screen="index", control_id="log_in_button"),
            note="Reversible: Log Out undoes it, so not risky.",
        ),
        Step(
            verb=StepVerb.WAIT_FOR,
            control=ControlRef(screen=NAV, control_id="log_out_link"),
            note=(
                "Waiting for the nav rather than the heading: logged-out "
                "overview.htm serves HTTP 200 with the SAME heading and an "
                "empty table, so the heading proves nothing."
            ),
        ),
        Step(
            verb=StepVerb.EXTRACT,
            control=ControlRef(screen="overview", control_id="welcome_name"),
            slot="first_name",
            output="customer_first_name",
            note="The welcome line is the only per-customer text on the screen.",
        ),
    ),
    checkpoints=(
        Checkpoint(
            output="customer_first_name",
            expected=LiteralValue(value="John"),
            why=(
                "A value, not a lookup. The credentials are fixed keys, so the "
                "customer behind them is fixed too -- a different name means the "
                "secret provider handed us somebody else's session."
            ),
        ),
    ),
)


READ_SAVINGS_BALANCE = Capability(
    name="read_savings_balance",
    version=1,
    goal="read the current balance of a member's savings account",
    vocabulary_version=VOCABULARY_VERSION,
    target=TARGET,
    viewport_width=_VIEWPORT.width,
    viewport_height=_VIEWPORT.height,
    params=(ParamSpec(name="account_id", slot="account_id"),),
    returns=(
        OutputSpec(name="found_account_id", slot="account_id"),
        OutputSpec(name="account_type", slot="account_type"),
        OutputSpec(name="balance", slot="balance"),
    ),
    requires=(
        Precondition(
            name="authenticated",
            control=ControlRef(screen=NAV, control_id="log_out_link"),
            must="present",
            why=(
                "Logged-out overview.htm returns HTTP 200 with the right heading "
                "and an empty table. A checkpoint cannot catch that; the presence "
                "of Log Out can. Re-checked on resume after a human handoff, "
                "because the operator may have logged out."
            ),
        ),
    ),
    steps=(
        Step(
            verb=StepVerb.CLICK,
            control=ControlRef(screen=NAV, control_id="accounts_overview_link"),
            note="Navigation only. Reversible.",
        ),
        Step(
            verb=StepVerb.WAIT_FOR,
            control=ControlRef(screen="overview", control_id="accounts_overview_heading"),
            note="The table renders after the nav, so the heading is the gate.",
        ),
        Step(
            verb=StepVerb.CLICK,
            control=ControlRef(
                screen="overview",
                control_id="account_link",
                discriminator=ParamValue(param="account_id"),
            ),
            note=(
                "The parameterised step, and the one with no mechanism behind it "
                "yet. Discovery slugs a control from its visible label, so this "
                "row records as `account_13344_link` -- an id that cannot serve "
                "another account. The discriminator says WHICH row by value; "
                "resolving it is docs/issues/0007."
            ),
        ),
        Step(
            verb=StepVerb.WAIT_FOR,
            control=ControlRef(screen="activity", control_id="account_details_heading"),
            note="Account Details. One screen per record id (activity.htm?id=:id).",
        ),
        Step(
            verb=StepVerb.OBSERVE,
            note="Evidence frame of the screen every value below is read from (S3.5).",
        ),
        Step(
            verb=StepVerb.EXTRACT,
            control=ControlRef(screen="activity", control_id="account_number_value"),
            slot="account_id",
            output="found_account_id",
            note="Read back the id we navigated to, so the checkpoint can compare it.",
        ),
        Step(
            verb=StepVerb.EXTRACT,
            control=ControlRef(screen="activity", control_id="account_type_value"),
            slot="account_type",
            output="account_type",
            note="The field that separates the seeded record from the CLEAN one.",
        ),
        Step(
            verb=StepVerb.EXTRACT,
            control=ControlRef(screen="activity", control_id="balance_value"),
            slot="balance",
            output="balance",
            note="What the caller asked for. Never asserted -- it is the answer.",
        ),
    ),
    checkpoints=(
        Checkpoint(
            output="found_account_id",
            expected=ParamValue(param="account_id"),
            why=(
                "Necessary and NOT sufficient: ParaBank's CLEAN state keeps id "
                "13344 and changes the record behind it, so this passes there."
            ),
        ),
        Checkpoint(
            output="account_type",
            expected=LiteralValue(value="SAVINGS"),
            why=(
                "This is the one that catches it. After CLEAN, 13344 is CHECKING "
                "$5,022.93 rather than SAVINGS $1,231.10 -- a different record "
                "under the same id. Without this the capability returns the wrong "
                "number to a bank and reports success."
            ),
        ),
    ),
)


REGISTRY: tuple[Capability, ...] = (LOG_IN, READ_SAVINGS_BALANCE)


def get(name: str) -> Capability:
    for capability in REGISTRY:
        if capability.name == name:
            return capability
    known = ", ".join(c.name for c in REGISTRY)
    raise KeyError(f"no capability named {name!r}; known: {known}")


def validate_all() -> None:
    for capability in REGISTRY:
        validate_capability(capability)
