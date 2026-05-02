from __future__ import annotations

import uuid
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from src.config import Settings, get_settings
from src.models.approval import Approval

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

_HEADER = ["approval_id", "post_id", "preview", "scheduled_at", "decision", "decided_by"]


class SheetsClient:
    """Thin wrapper around gspread for the approval sheet."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._gc: Optional[gspread.Client] = None
        self._ws: Optional[gspread.Worksheet] = None

    def _worksheet(self) -> gspread.Worksheet:
        if self._ws is not None:
            return self._ws
        creds = Credentials.from_service_account_file(
            self._settings.google_sheets_credentials_file,
            scopes=_SCOPES,
        )
        self._gc = gspread.authorize(creds)
        sheet = self._gc.open_by_key(self._settings.google_sheet_id)
        try:
            self._ws = sheet.worksheet("approvals")
        except gspread.WorksheetNotFound:
            self._ws = sheet.add_worksheet(title="approvals", rows=1000, cols=len(_HEADER))
            self._ws.append_row(_HEADER)
        return self._ws

    def append_row(self, approval: Approval) -> int:
        """Append an approval row and return its 1-based row index."""
        ws = self._worksheet()
        row = [
            str(approval.id),
            str(approval.post_id),
            approval.preview_text[:500],
            str(approval.scheduled_at) if approval.scheduled_at else "",
            approval.decision,
            "",
        ]
        ws.append_row(row, value_input_option="RAW")
        return len(ws.get_all_values())

    def read_decisions(self) -> list[dict]:
        """Return rows where decision is not 'pending' and approval_id is a valid UUID."""
        ws = self._worksheet()
        rows = ws.get_all_records(expected_headers=_HEADER)
        decisions = []
        for row in rows:
            if row.get("decision") not in ("approved", "rejected"):
                continue
            try:
                approval_id = uuid.UUID(str(row["approval_id"]))
            except (ValueError, KeyError):
                continue
            decisions.append(
                {
                    "approval_id": approval_id,
                    "decision": row["decision"],
                    "decided_by": row.get("decided_by") or "sheet",
                }
            )
        return decisions

    def update_decision(self, approval_id: uuid.UUID, decision: str) -> None:
        """Write a decision back to the sheet row matching approval_id."""
        ws = self._worksheet()
        cell = ws.find(str(approval_id), in_column=1)
        if cell is None:
            return
        decision_col = _HEADER.index("decision") + 1
        ws.update_cell(cell.row, decision_col, decision)
