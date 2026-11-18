"""Projects GTD — the web app's board API, under /api/app beside the todo app's.

Same rules as router.build_router: a signed-in browser on the list it names in
X-List (router.active_owner), same-origin non-GETs, no-store, no DELETE routes.

    GET  /boards[?status=archived]   the projects, with column card counts
    POST /boards                     a new project (To do / Doing / Done)
    GET  /boards/{id}                one board: columns with their cards
    PUT  /boards/{id}                rename, notes, archive / restore
    GET  /boards/{id}/archived       its archived cards, 200 a page (?offset=)
    POST /boards/{id}/columns        add a column
    PUT  /columns/{id}               rename, reorder, archive / restore a column
    POST /columns/{id}/move-cards    move all its cards to another column (Trello's)
    POST /columns/{id}/archive-cards archive all its cards
    POST /columns/{id}/sort          sort its cards once: due, created, newest or title
    GET  /boards/{id}/labels         the project's labels   POST: add one
    PUT  /labels/{id}                rename, recolour, archive / restore a label
    POST /boards/{id}/cards          add a card
    GET  /cards/{id}                 one card, archived or not
    PUT  /cards/{id}                 edit, complete / re-open, hold, archive / restore a card
    POST /cards/{id}/move            move a card to a column and position, on or off hold, or to a project
    POST /cards/{id}/copy            copy a card (or make one from a card template)
    GET  /boards/{id}/rules          its automation: rules, card buttons, board buttons   POST: add one
    PUT  /rules/{id}                 change, archive or restore a rule or button
    POST /rules/{id}/press           press a button (a card button names its card)
"""

from fastapi import APIRouter, Depends, Query

from backend import automation, boards
from backend.models import (
    BoardCreate,
    BoardUpdate,
    CardCopy,
    CardCreate,
    CardMove,
    CardUpdate,
    ColumnCards,
    ColumnCreate,
    ColumnSort,
    ColumnUpdate,
    LabelCreate,
    LabelUpdate,
    RuleCreate,
    RulePress,
    RuleUpdate,
)
from backend.router import _call, active_owner

router = APIRouter(prefix="/api/app", dependencies=[Depends(active_owner)])


@router.get("/boards")
def list_boards(status: str = "active", owner: int = Depends(active_owner)):
    return {"boards": _call(boards.list_boards, owner, status)}


@router.post("/boards")
def create_board(body: BoardCreate, owner: int = Depends(active_owner)):
    return _call(boards.create_board, owner, body.name, body.notes, body.columns, tools=body.tools)


@router.get("/boards/{board_id}")
def get_board(board_id: int, owner: int = Depends(active_owner)):
    return _call(boards.get_board, owner, board_id)


@router.put("/boards/{board_id}")
def update_board(board_id: int, body: BoardUpdate, owner: int = Depends(active_owner)):
    return _call(boards.update_board, owner, board_id, body.model_dump(exclude_unset=True))


@router.get("/boards/{board_id}/archived")
def archived_cards(board_id: int, offset: int = Query(default=0, ge=0), owner: int = Depends(active_owner)):
    return {"cards": _call(boards.archived_cards, owner, board_id, offset=offset)}


@router.post("/boards/{board_id}/columns")
def add_column(board_id: int, body: ColumnCreate, owner: int = Depends(active_owner)):
    return _call(boards.add_column, owner, board_id, body.name, body.position)


@router.put("/columns/{column_id}")
def update_column(column_id: int, body: ColumnUpdate, owner: int = Depends(active_owner)):
    return _call(boards.update_column, owner, column_id, body.model_dump(exclude_unset=True))


@router.post("/columns/{column_id}/move-cards")
def move_all_cards(column_id: int, body: ColumnCards, owner: int = Depends(active_owner)):
    return _call(boards.move_all_cards, owner, column_id, body.to_column_id)


@router.post("/columns/{column_id}/archive-cards")
def archive_all_cards(column_id: int, owner: int = Depends(active_owner)):
    return _call(boards.archive_all_cards, owner, column_id)


@router.post("/columns/{column_id}/sort")
def sort_column(column_id: int, body: ColumnSort, owner: int = Depends(active_owner)):
    return _call(boards.sort_column, owner, column_id, body.by)


@router.get("/boards/{board_id}/labels")
def list_labels(board_id: int, status: str = "active", owner: int = Depends(active_owner)):
    return {"labels": _call(boards.list_labels, owner, board_id, status)}


@router.post("/boards/{board_id}/labels")
def create_label(board_id: int, body: LabelCreate, owner: int = Depends(active_owner)):
    return _call(boards.create_label, owner, board_id, body.name, body.color)


@router.put("/labels/{label_id}")
def update_label(label_id: int, body: LabelUpdate, owner: int = Depends(active_owner)):
    return _call(boards.update_label, owner, label_id, body.model_dump(exclude_unset=True))


@router.post("/boards/{board_id}/cards")
def create_card(board_id: int, body: CardCreate, owner: int = Depends(active_owner)):
    extra = body.model_dump(
        exclude_unset=True, include={"starts_on", "assignee_ids", "labels", "cover", "repeat", "template"}
    )
    return _call(
        boards.create_card,
        owner,
        board_id,
        body.title,
        column=body.column_id,
        notes=body.notes,
        due_date=body.due_date,
        position=body.position,
        source="ui",
        **extra,
    )


@router.get("/cards/{card_id}")
def get_card(card_id: int, owner: int = Depends(active_owner)):
    """One card, archived ones too (a link to an archived card opens it)."""
    return _call(boards.get_card, owner, card_id)


@router.put("/cards/{card_id}")
def update_card(card_id: int, body: CardUpdate, owner: int = Depends(active_owner)):
    """409 when ``version`` is given and the card has changed since."""
    fields = body.model_dump(exclude_unset=True)
    version = fields.pop("version", None)
    return _call(boards.update_card, owner, card_id, fields, version)


@router.post("/cards/{card_id}/move")
def move_card(card_id: int, body: CardMove, owner: int = Depends(active_owner)):
    column = body.column_id if body.column_id is not None else "triage"
    return _call(boards.move_card, owner, card_id, column, body.position, body.project_id, on_hold=body.on_hold)


@router.get("/card-templates")
def card_templates(owner: int = Depends(active_owner)):
    return {"templates": _call(boards.card_templates, owner)}


@router.post("/cards/{card_id}/copy")
def copy_card(card_id: int, body: CardCopy, owner: int = Depends(active_owner)):
    return _call(boards.copy_card, owner, card_id, column=body.column_id, board=body.project_id, title=body.title)


# ── Automation ────────────────────────────────────────────────────────────────


@router.get("/boards/{board_id}/rules")
def list_rules(board_id: int, status: str = "active", owner: int = Depends(active_owner)):
    return {"rules": _call(automation.list_rules, owner, board_id, status)}


@router.post("/boards/{board_id}/rules")
def create_rule(board_id: int, body: RuleCreate, owner: int = Depends(active_owner)):
    return _call(automation.create_rule, owner, board_id, body.kind, body.name, body.trigger, body.actions)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleUpdate, owner: int = Depends(active_owner)):
    return _call(automation.update_rule, owner, rule_id, body.model_dump(exclude_unset=True))


@router.post("/rules/{rule_id}/press")
def press_rule(rule_id: int, body: RulePress, owner: int = Depends(active_owner)):
    return _call(automation.press, owner, rule_id, body.card_id)
