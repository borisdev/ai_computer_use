"""ParaBank: what the target surface is, and how to put it into known states.

ParaBank is Parasoft's demo bank (https://github.com/parasoft/parabank) -- a
Spring MVC + JSP app on Tomcat backed by HSQLDB. It is a good proxy for the
assignment's environment because it is genuinely legacy-shaped: server-rendered
`.htm` form posts, table-based layout, no `data-testid` anywhere, and a REST API
that exists but which we deliberately do not use for the automation itself.

Everything in FIXTURES below is read off the app's own seed script
(src/main/resources/com/parasoft/parabank/dao/jdbc/sql/insert.sql at master) and
the AccountType enum in domain/Account.java, where 0=CHECKING, 1=SAVINGS,
2=LOAN. It has NOT yet been confirmed against a running container -- verify on
first boot before trusting a balance as a replay checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import httpx

from interfaceai.settings import get_settings


@dataclass(frozen=True)
class Account:
    id: int
    customer_id: int
    type: str
    balance: Decimal


@dataclass(frozen=True)
class Customer:
    id: int
    username: str
    first_name: str
    last_name: str


# --- Seed fixtures (present after a DB init) --------------------------------

CUSTOMERS: tuple[Customer, ...] = (
    Customer(id=12212, username="john", first_name="John", last_name="Smith"),
    Customer(id=12323, username="parasoft", first_name="Bob", last_name="Parasoft"),
)

ACCOUNTS: tuple[Account, ...] = (
    Account(12345, 12212, "CHECKING", Decimal("-2300.00")),
    Account(12456, 12212, "CHECKING", Decimal("10.45")),
    Account(12567, 12212, "CHECKING", Decimal("100.00")),
    Account(12678, 12212, "SAVINGS", Decimal("-100.00")),
    Account(12789, 12212, "CHECKING", Decimal("100.00")),
    Account(12900, 12212, "CHECKING", Decimal("0.00")),
    Account(13011, 12212, "CHECKING", Decimal("100.00")),
    Account(13122, 12212, "CHECKING", Decimal("1100.00")),
    Account(13233, 12212, "CHECKING", Decimal("100.00")),
    Account(13344, 12212, "SAVINGS", Decimal("1231.10")),
    Account(54321, 12212, "CHECKING", Decimal("1351.12")),
    Account(13455, 12323, "CHECKING", Decimal("2014.76")),
)

# The assignment's worked example is "look up member 12345 and read their
# current savings balance". On ParaBank that maps to john's savings account.
DEMO_SAVINGS_ACCOUNT_ID = 13344
DEMO_SAVINGS_BALANCE = Decimal("1231.10")

# An id in no seed row, in either state -- drives the "no such account" business
# outcome, which the assignment is explicit must not be reported as a crash.
MISSING_ACCOUNT_ID = 99999

# --- The second state: what `CLEAN` leaves behind -----------------------------
#
# ParaBank's CLEAN is not a wipe. It runs reset.sql, which DELETEs every table
# and then re-inserts a single customer and a single account:
#
#     INSERT INTO Account VALUES (13344, 12212, 0, '5022.93');
#
# So account 13344 survives, but as CHECKING $5,022.93 rather than SAVINGS
# $1,231.10 -- the same id, a different record. Two useful failure modes fall
# out of one lever:
#
#   * every other account (12345, 54321, ...) is genuinely gone, so a lookup
#     legitimately finds nothing -- the business-outcome branch
#   * 13344 still resolves, but violates a checkpoint recorded against the INIT
#     state. A replay that reports $5,022.93 as a savings balance has silently
#     returned the wrong number to a bank, which is the failure that matters
CLEAN_STATE_ACCOUNTS: tuple[Account, ...] = (Account(13344, 12212, "CHECKING", Decimal("5022.93")),)

# App parameters, also seeded. minimum_balance is the lever that produces a
# real validation error on a transfer without any code change.
INITIAL_BALANCE = Decimal("515.50")
MINIMUM_BALANCE = Decimal("100.00")


# --- Known states, for evidence and error injection -------------------------
#
# The assignment wants a replay that hits an error or exceptional state. These
# are ParaBank's own admin controls, so we inject failures the way an operator
# could -- no monkeypatching, no fault-injection proxy in front of the app.


class ParaBankAdmin:
    """Drive ParaBank's admin page to put the app into a known state.

    The admin form endpoints are read from the app's own JSP
    (webapp/WEB-INF/jsp/content/admin.jsp): `db.htm` takes action=INIT|CLEAN and
    `jms.htm` takes shutdown=<bool>. Unverified against a running instance.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = (base_url or get_settings().parabank_base_url).rstrip("/")
        self._timeout = timeout

    def _post(self, path: str, data: dict[str, str]) -> httpx.Response:
        with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
            response = client.post(f"{self.base_url}/{path}", data=data)
            response.raise_for_status()
            return response

    def init_db(self) -> None:
        """Reseed to the fixtures above. Run before any recorded replay."""
        self._post("db.htm", {"action": "INIT"})

    def clean_db(self) -> None:
        """Drop to the minimal dataset -- NOT a wipe. See CLEAN_STATE_ACCOUNTS.

        Leaves one customer and one account behind, so it exercises both the
        'record not found' branch and the 'checkpoint violated' branch of the
        replay result contract, against the real app rather than a stub.
        """
        self._post("db.htm", {"action": "CLEAN"})

    def set_jms(self, *, running: bool) -> None:
        """Stop/start the loan processor queue -- a backend-down failure mode."""
        self._post("jms.htm", {"shutdown": str(not running).lower()})


def is_up(base_url: str | None = None, timeout: float = 5.0) -> bool:
    """True once Tomcat has deployed the webapp and the landing page renders.

    Liveness only. ParaBank serves HTML happily with no database schema behind
    it, so this returning True says nothing about whether a lookup will work --
    see is_seeded().
    """
    url = (base_url or get_settings().parabank_base_url).rstrip("/")
    try:
        response = httpx.get(f"{url}/index.htm", timeout=timeout, follow_redirects=True)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def is_seeded(base_url: str | None = None, timeout: float = 5.0) -> bool:
    """True once the schema exists and the fixtures are loaded.

    ParaBank boots with no schema at all. `IndexController` tries to create it
    lazily on a hit to index.htm, and that path is unreliable -- observed
    retrying every 10s indefinitely without ever completing, while the app kept
    serving 200s and the compose healthcheck stayed green. The dependable route
    is an explicit POST to db.htm (see ParaBankAdmin.init_db).

    Readiness, not liveness. This is what `make up` gates on.
    """
    url = (base_url or get_settings().parabank_base_url).rstrip("/")
    try:
        response = httpx.get(
            f"{url}/services/bank/accounts/{DEMO_SAVINGS_ACCOUNT_ID}",
            headers={"Accept": "application/json"},
            timeout=timeout,
            follow_redirects=True,
        )
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    try:
        return response.json().get("id") == DEMO_SAVINGS_ACCOUNT_ID
    except ValueError:
        return False
