from __future__ import annotations

from dataclasses import asdict, dataclass


VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
VISIBLE_STATUSES = {"pending", "in_progress"}


@dataclass
class TodoItem:
    content: str
    status: str = "pending"
    active_form: str = ""
    id: str = ""


class TodoStore:
    def __init__(self) -> None:
        self._items: list[TodoItem] = []

    def replace(self, items: list[TodoItem | dict]) -> list[dict]:
        next_items = [self._coerce(item) for item in items]
        self._validate(next_items)
        self._items = next_items
        return self.items()

    def items(self) -> list[dict]:
        return [asdict(item) for item in self._items]

    def active_items(self) -> list[dict]:
        return [asdict(item) for item in self._items if item.status in VISIBLE_STATUSES]

    def format_for_injection(self) -> str:
        visible = [item for item in self._items if item.status in VISIBLE_STATUSES]
        if not visible:
            return "## Task Progress\n(no active todo)"
        lines = [
            "## Task Progress",
            "Current execution todo. Keep approval plans and durable background tasks separate.",
        ]
        marks = {"pending": "[ ]", "in_progress": "[>]"}
        for item in visible:
            label = item.active_form if item.status == "in_progress" and item.active_form else item.content
            lines.append(f"{marks[item.status]} {label}")
        return "\n".join(lines)

    def _coerce(self, item: TodoItem | dict) -> TodoItem:
        if isinstance(item, TodoItem):
            return item
        return TodoItem(
            id=str(item.get("id", "")),
            content=str(item.get("content", "")),
            status=str(item.get("status", "pending")),
            active_form=str(item.get("active_form") or item.get("activeForm") or ""),
        )

    def _validate(self, items: list[TodoItem]) -> None:
        in_progress_count = 0
        for item in items:
            if not item.content.strip():
                raise ValueError("todo content cannot be empty")
            if item.status not in VALID_STATUSES:
                raise ValueError(f"invalid todo status: {item.status}")
            if item.status == "in_progress":
                in_progress_count += 1
        if in_progress_count > 1:
            raise ValueError("at most one in_progress todo item is allowed")
