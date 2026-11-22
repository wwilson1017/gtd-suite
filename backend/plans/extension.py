"""The optional extension: off when not installed. A hosted deployment may install a
separate package, gtd_extension, that adds to the account levels (plans.py); every name
below then hands over to it. Without it each answers "nothing": no extra routes, notes,
pages or commands, and levels come only from FREE_MAX and the operator's grants.
"""

import functools
import importlib
from types import ModuleType

from backend import db


class ExtensionError(Exception):
    """The extension's outside service failed or could not be reached (its errors are these)."""


# The lists.stripe_customer column: an account the extension tied to an outside account.
NO_CUSTOMER_SQL = "stripe_customer = ''"


@functools.cache
def _package() -> ModuleType | None:
    try:
        return importlib.import_module("gtd_extension")
    except ModuleNotFoundError as e:
        if e.name != "gtd_extension":
            raise  # the package is there but broken: say so rather than run without it
        return None


def offers() -> bool:
    """Whether the extension offers anything to accounts here (/api/config's ``offers``)."""
    package = _package()
    return bool(package and package.offers())


def cap_note(eligible: bool, to: int | None = None) -> str:
    """A sentence a cap refusal adds about raising the cap, or ''."""
    package = _package()
    return package.cap_note(eligible, to) if package else ""


def guide_note() -> str:
    """How the guide's ``limits`` says caps are raised, or ''."""
    package = _package()
    return package.guide_note() if package else ""


def guide_lines() -> list[str]:
    package = _package()
    return package.guide_lines() if package else []


def session(row) -> dict:
    """What the extension adds to the session's ``plan`` block."""
    package = _package()
    return package.session(row) if package else {}


def email_confirmed(list_id: int) -> None:
    """After the response to a sign-in that confirmed the account's email."""
    package = _package()
    if package:
        package.email_confirmed(list_id)


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


def page(name: str) -> str | None:
    """The extension's own version of a one-segment page (/terms.html …), or None."""
    package = _package()
    return package.page(name) if package else None


def _refuse_customer(list_id: int, what: str) -> None:
    customer = (
        db.get_db().execute("SELECT stripe_customer FROM lists WHERE id = ?", (list_id,)).fetchone()["stripe_customer"]
    )
    if customer:
        raise SystemExit(
            f"List {list_id} is tied to an outside account ({customer}); run this where the extension "
            f"is installed so it can be checked. {what}"
        )


def check_disable(list_id: int) -> None:
    """admin.py disable: the extension refuses (SystemExit) an account it must settle first."""
    package = _package()
    if package:
        package.check_disable(list_id)
    else:
        _refuse_customer(list_id, "Nothing changed.")


def check_delete(list_id: int) -> None:
    """admin.py delete: never delete the row that ties an outside account to its account."""
    package = _package()
    if package:
        package.check_delete(list_id)
    else:
        _refuse_customer(list_id, "Nothing was deleted.")
