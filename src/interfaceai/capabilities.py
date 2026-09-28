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

`read_savings_balance` is the assignment's own worked example. **v2 reads the
accounts table as a `TABLE_CONTROL_PANEL`** -- one model call returns every row,
and the caller's `account_id` selects one IN CODE. No row is grounded, nothing
is asked where account 13344 is, and `docs/issues/0009` (wrong-row grounding,
3 in 4) is off its path entirely.

⚠️ **Capability 1 INVOKES `log_in` rather than copying it.** That is the point
of having a vocabulary: a small canonical set composes. The version is pinned,
so a new `log_in` cannot silently change what replay does.

⚠️ **v3 restores the checkpoint v2 gave up.** v1 drilled into `activity.htm`
by grounding the account's row link -- which lands on the WRONG row 3 times in
4, silently (`docs/issues/0009`). v2 dropped the drilldown and with it the
`account_type == SAVINGS` check, so it reported the balance of whatever 13344
had become. v3 drills in again, but by ARITHMETIC: the row index comes from the
panel read and the y from the measured 28px rhythm, so nothing is ever asked
where a row is. The panel read is reused, so the drilldown costs no extra model
call.
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
    version=2,
    goal="log in to the bank as the operator's seeded customer",
    vocabulary_version=VOCABULARY_VERSION,
    target=TARGET,
    viewport_width=_VIEWPORT.width,
    viewport_height=_VIEWPORT.height,
    # No params. Credentials are NOT caller arguments -- they are names the
    # runtime resolves from a secret provider, so nothing about them reaches
    # this file or the artifact on disk.
    params=(),
    returns=(),
    requires=(
        Precondition(
            name="at_the_login_page",
            control=ControlRef(screen="index", control_id="username_textbox"),
            must="present",
            why=(
                "Logging in on top of a live session lands on a different screen than "
                "the one these steps were recorded against. Re-checked on resume, "
                "since a human handed the browser back may have navigated anywhere."
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
            note="Same. `use_control` records value_length and never the value.",
        ),
        Step(
            verb=StepVerb.CLICK,
            control=ControlRef(screen="index", control_id="log_in_button"),
            note="Reversible: logging out undoes it, so not risky.",
        ),
        Step(
            verb=StepVerb.WAIT_FOR,
            control=ControlRef(screen="overview", control_id="accounts_overview_link"),
            note=(
                "Waiting for the account-services nav, not a heading: logged-out "
                "overview.htm serves HTTP 200 with the SAME heading and an empty "
                "table. Measured -- every nav control is absent at 0.0000 when "
                "logged out, so its presence is what proves the session."
            ),
        ),
    ),
    # No checkpoint of its own: reaching the authenticated nav IS the success
    # condition, and it is already asserted by the wait above. A capability that
    # returns nothing has nothing to compare.
    checkpoints=(),
)


READ_SAVINGS_BALANCE = Capability(
    name="read_savings_balance",
    version=3,
    goal="read the current balance of a member's savings account",
    vocabulary_version=VOCABULARY_VERSION,
    target=TARGET,
    viewport_width=_VIEWPORT.width,
    viewport_height=_VIEWPORT.height,
    params=(ParamSpec(name="account_id", slot="account_id"),),
    returns=(
        OutputSpec(name="found_account_id", slot="account_id"),
        OutputSpec(name="balance", slot="balance"),
        OutputSpec(name="account_type", slot="account_type"),
    ),
    requires=(
        Precondition(
            name="at_the_login_page",
            control=ControlRef(screen="index", control_id="username_textbox"),
            must="present",
            why=(
                "This capability establishes its session by invoking `log_in`, which "
                "starts from the login screen. Re-checked on resume."
            ),
        ),
    ),
    steps=(
        # The whole argument for a vocabulary rather than a macro: `log_in` is
        # written once and every capability needing a session calls it. Copying
        # its three steps in here would mean re-fixing twenty artifacts the day
        # the login page moves.
        Step(
            verb=StepVerb.INVOKE,
            invokes="log_in",
            invokes_version=2,
            note="Establish a session. Its own precondition checks we are at the login page.",
        ),
        Step(
            verb=StepVerb.WAIT_FOR,
            control=ControlRef(screen="overview", control_id="accounts_table_panel"),
            note="The table's own header is the anchor -- unique, unlike any of its rows.",
        ),
        Step(
            verb=StepVerb.OBSERVE,
            note="Evidence frame of the screen the values below are read from (S3.5).",
        ),
        Step(
            verb=StepVerb.EXTRACT,
            control=ControlRef(screen="overview", control_id="accounts_table_panel"),
            slot="account_id",
            output="found_account_id",
            row_key=ParamValue(param="account_id"),
            field="account_id",
            note=(
                "Read the WHOLE table in one call, then select the row in code. "
                "Reading the id back is what lets the checkpoint prove we answered "
                "about the account the caller asked for."
            ),
        ),
        Step(
            verb=StepVerb.EXTRACT,
            control=ControlRef(screen="overview", control_id="accounts_table_panel"),
            slot="balance",
            output="balance",
            row_key=ParamValue(param="account_id"),
            field="balance",
            note="What the caller asked for. Never asserted -- it is the answer.",
        ),
        # The drilldown. Its click position comes from the row INDEX and the
        # measured 28px rhythm, never from grounding the row -- which lands on
        # the wrong record 3 times in 4, silently (docs/issues/0009). The panel
        # read above is reused, so this costs no extra model call.
        Step(
            verb=StepVerb.CLICK,
            control=ControlRef(screen="overview", control_id="accounts_table_panel"),
            row_key=ParamValue(param="account_id"),
            note="Open this account's detail page. Navigation only; reversible.",
        ),
        Step(
            verb=StepVerb.WAIT_FOR,
            control=ControlRef(screen="activity", control_id="account_details_panel"),
            note="Account Details. One screen per record id (activity.htm?id=:id).",
        ),
        Step(
            verb=StepVerb.EXTRACT,
            control=ControlRef(screen="activity", control_id="account_details_panel"),
            slot="account_type",
            output="account_type",
            row_key=LiteralValue(value="Account Type:"),
            field="value",
            note=(
                "The field that separates the seeded record from the CLEAN one, and "
                "the only reason this capability visits the detail page at all."
            ),
        ),
    ),
    checkpoints=(
        Checkpoint(
            output="found_account_id",
            expected=ParamValue(param="account_id"),
            why=(
                "The row we read must be the row that was asked for. An account that "
                "is absent entirely is a business outcome, not this."
            ),
        ),
        Checkpoint(
            output="account_type",
            expected=LiteralValue(value="SAVINGS"),
            why=(
                "This is the one that catches a changed record. After ParaBank's "
                "CLEAN, account 13344 still resolves -- as CHECKING $5,022.93 rather "
                "than SAVINGS $1,231.10. Without this the capability returns the "
                "wrong number to a bank and reports success."
            ),
        ),
    ),
)


REQUEST_LOAN = Capability(
    name="request_loan",
    version=1,
    goal="apply for a loan of a given amount with a given down payment",
    vocabulary_version=VOCABULARY_VERSION,
    target=TARGET,
    viewport_width=_VIEWPORT.width,
    viewport_height=_VIEWPORT.height,
    params=(
        ParamSpec(name="amount", slot="amount"),
        ParamSpec(name="down_payment", slot="down_payment"),
    ),
    returns=(),
    requires=(
        Precondition(
            name="at_the_login_page",
            control=ControlRef(screen="index", control_id="username_textbox"),
            must="present",
            why="This capability establishes its session by invoking `log_in`.",
        ),
    ),
    steps=(
        Step(
            verb=StepVerb.INVOKE,
            invokes="log_in",
            invokes_version=2,
            note="Establish a session.",
        ),
        # ⛔ Through the NAV PANEL, not by clicking `request_loan_link`.
        #
        # The nav is a vertical list of eight near-identical links, and
        # grounding scores **0 of 8** on it -- `request_loan_link` lands on
        # Transfer Funds, which is exactly where an earlier version of this
        # capability ended up. That is `docs/issues/0009` outside a table, and
        # it is why the rule is "repeated structures need panels" rather than
        # "tables need panels".
        Step(
            verb=StepVerb.CLICK,
            control=ControlRef(screen="overview", control_id="account_services_nav"),
            row_key=LiteralValue(value="Request Loan"),
            note="Navigation only, by row key. Reversible.",
        ),
        Step(
            verb=StepVerb.WAIT_FOR,
            control=ControlRef(screen="requestloan", control_id="loan_amount_textbox"),
            note="The loan form.",
        ),
        Step(
            verb=StepVerb.ENTER,
            control=ControlRef(screen="requestloan", control_id="loan_amount_textbox"),
            slot="amount",
            value=ParamValue(param="amount"),
            note=(
                "Typing an amount is harmless -- nothing has moved. The value is "
                "remembered and judged at the irreversible step below."
            ),
        ),
        Step(
            verb=StepVerb.ENTER,
            control=ControlRef(screen="requestloan", control_id="down_payment_textbox"),
            slot="down_payment",
            value=ParamValue(param="down_payment"),
            note="A second money field, so the rule must consider both.",
        ),
        # ⛔ The irreversible step. `apply_now_button` carries
        # `ControlPolicy.irreversible` in the control map, so ANY capability
        # touching it inherits the requirement -- no author has to remember.
        #
        # With a tenant threshold configured, a large enough amount stops the
        # run HERE and hands the session to a person. That is why every live
        # test of this capability uses an amount over the threshold: the loan
        # is never actually submitted, so the fixtures stay clean.
        Step(
            verb=StepVerb.CLICK,
            control=ControlRef(screen="requestloan", control_id="apply_now_button"),
            note="Submits a loan application. Irreversible.",
        ),
    ),
    # Nothing is returned, so nothing needs checking -- reaching the submit is
    # the whole of this capability, and the confirmation gate is the point.
    checkpoints=(),
)


REGISTRY: tuple[Capability, ...] = (LOG_IN, READ_SAVINGS_BALANCE, REQUEST_LOAN)

LIBRARY: dict[str, Capability] = {c.name: c for c in REGISTRY}
"""What an `invoke` step resolves against. Keyed by name; the STEP pins the
version, so a library holding a newer one is a validation error rather than a
silent substitution."""


def get(name: str) -> Capability:
    for capability in REGISTRY:
        if capability.name == name:
            return capability
    known = ", ".join(c.name for c in REGISTRY)
    raise KeyError(f"no capability named {name!r}; known: {known}")


def validate_all() -> None:
    for capability in REGISTRY:
        validate_capability(capability)
