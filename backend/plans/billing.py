"""The billing seam: off here. Selling plans is a separate package, gtd_billing, which this
open-source build does not include. When it is installed, every name below hands over to it;
without it nothing is sold or synced, no billing route exists, and plans come only from
the free switch and the operator's grants (plans.of).
"""

import functools
import importlib
from types import ModuleType

from backend import db


class BillingError(Exception):
    """The payment service failed or could not be reached (the package's errors are these)."""


NO_CUSTOMER_SQL = "stripe_customer = ''"


@functools.cache
def _package() -> ModuleType | None:
    try:
        return importlib.import_module("gtd_billing")
    except ModuleNotFoundError as e:
        if e.name != "gtd_billing":
            raise  # the package is there but broken: say so rather than run as if free
        return None


def syncing() -> bool:
    package = _package()
    return bool(package and package.syncing())


def selling() -> bool:
    package = _package()
    return bool(package and package.selling())


def upsell(eligible: bool, to: int | None = None) -> str:
    """The sentence a cap refusal adds about a plan that raises it, or ''."""
    package = _package()
    return package.upsell(eligible, to) if package else ""


def guide_upsell() -> str:
    package = _package()
    return package.guide_upsell() if package else ""


def push_email(list_id: int) -> bool:
    package = _package()
    return package.push_email(list_id) if package else True


async def maintain() -> None:
    package = _package()
    if package:
        await package.maintain()


def mount(router, account_router, session_owner, base_url) -> None:
    package = _package()
    if package:
        package.mount(router, account_router, session_owner, base_url)


def admin_commands(command) -> None:
    package = _package()
    if package:
        package.register(command)


def policy_page(name: str) -> str | None:
    """The package's own version of a policy page, or None for the public one."""
    package = _package()
    return package.policy_page(name) if package else None


def _refuse_customer(list_id: int, what: str) -> None:
    customer = (
        db.get_db().execute("SELECT stripe_customer FROM lists WHERE id = ?", (list_id,)).fetchone()["stripe_customer"]
    )
    if customer:
        raise SystemExit(
            f"List {list_id} is a billing customer ({customer}); run this where the billing package "
            f"is installed so it can be checked. {what}"
        )


def refuse_while_subscribed(list_id: int) -> None:
    """admin.py disable: never disable an account that billing could still charge."""
    package = _package()
    if package:
        package.refuse_while_subscribed(list_id)
    else:
        _refuse_customer(list_id, "Nothing changed.")


def refuse_while_billable(list_id: int) -> None:
    """admin.py delete: never delete the row that ties a billing customer to its account."""
    package = _package()
    if package:
        package.refuse_while_billable(list_id)
    else:
        _refuse_customer(list_id, "Nothing was deleted.")
