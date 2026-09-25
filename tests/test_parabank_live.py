"""Live checks against a running ParaBank. Run with: make smoke

Marked `live` so the offline suite stays runnable with nothing started.
"""

import httpx
import pytest

from interfaceai import parabank
from interfaceai.settings import get_settings

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def base_url() -> str:
    url = get_settings().parabank_base_url
    if not parabank.is_up(url):
        pytest.skip(f"ParaBank is not running at {url} -- `make up` first")
    return url


def test_landing_page_renders(base_url: str) -> None:
    response = httpx.get(f"{base_url}/index.htm", timeout=15, follow_redirects=True)
    assert response.status_code == 200
    assert "ParaBank" in response.text


def test_login_form_is_present(base_url: str) -> None:
    """The surface we automate: a plain form post, no test IDs, no SPA."""
    response = httpx.get(f"{base_url}/index.htm", timeout=15, follow_redirects=True)
    assert 'name="username"' in response.text
    assert 'name="password"' in response.text


def test_admin_page_is_reachable(base_url: str) -> None:
    """We drive this page to inject known failure states on replay."""
    response = httpx.get(f"{base_url}/admin.htm", timeout=15, follow_redirects=True)
    assert response.status_code == 200


def test_seeded_savings_balance_matches_the_fixture_table(base_url: str) -> None:
    """Confirms the constants read out of insert.sql survive a real boot.

    Uses ParaBank's REST API purely as an oracle. The automation under test
    never touches it -- the whole premise is that a real bank app has no API.
    """
    account_id = parabank.DEMO_SAVINGS_ACCOUNT_ID
    response = httpx.get(
        f"{base_url}/services/bank/accounts/{account_id}",
        headers={"Accept": "application/json"},
        timeout=15,
        follow_redirects=True,
    )
    if response.status_code == 404:
        pytest.skip("REST oracle not exposed at this path on this build")
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "SAVINGS"
    assert float(body["balance"]) == float(parabank.DEMO_SAVINGS_BALANCE)
