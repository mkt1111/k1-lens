"""Review-queue errors."""


class DocumentNotFoundError(Exception):
    """No document with that id is in the queue."""


class InvalidFieldValueError(Exception):
    """A reviewer submitted a value the field cannot store."""


class ApprovalBlockedError(Exception):
    """Approve or export was refused because review items are still open."""

    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__("; ".join(issues))
