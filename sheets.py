import os
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

HEADERS = ["ID", "Task", "Category", "Priority", "Owner", "Source", "Ticket", "Deadline", "Status", "Created At"]

_client = None
_sheet = None


def _get_sheet():
    global _client, _sheet
    if _sheet is not None:
        return _sheet

    import json
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")

    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    elif os.path.isfile(creds_path):
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    else:
        # last resort: treat GOOGLE_CREDENTIALS_PATH value as raw JSON
        try:
            creds_dict = json.loads(creds_path)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        except Exception:
            raise RuntimeError("No valid Google credentials found. Set GOOGLE_CREDENTIALS_JSON.")
    _client = gspread.authorize(creds)

    spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")
    spreadsheet = _client.open_by_key(spreadsheet_id)

    try:
        _sheet = spreadsheet.worksheet("Tasks")
    except gspread.WorksheetNotFound:
        _sheet = spreadsheet.add_worksheet(title="Tasks", rows=1000, cols=20)
        _sheet.append_row(HEADERS)

    # Ensure headers exist
    first_row = _sheet.row_values(1)
    if first_row != HEADERS:
        _sheet.insert_row(HEADERS, 1)

    return _sheet


def _next_id(sheet) -> int:
    values = sheet.col_values(1)[1:]  # Skip header
    ids = [int(v) for v in values if v.isdigit()]
    return max(ids, default=0) + 1


def add_task(task: str, category: str, priority: str, owner: str, source: str = "manual", ticket: str = None, deadline: str = None) -> int:
    sheet = _get_sheet()
    row_id = _next_id(sheet)
    created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    row = [row_id, task, category, priority, owner, source, ticket or "", deadline or "", "todo", created_at]
    sheet.append_row(row)
    return row_id


def list_tasks(status_filter: str = None) -> list[dict]:
    sheet = _get_sheet()
    rows = sheet.get_all_records()
    result = []
    for r in rows:
        if status_filter and r.get("Status", "").lower() != status_filter.lower():
            continue
        if not status_filter and r.get("Status", "").lower() == "done":
            continue
        result.append({
            "id": r.get("ID"),
            "task": r.get("Task"),
            "category": r.get("Category"),
            "priority": r.get("Priority"),
            "owner": r.get("Owner"),
            "source": r.get("Source"),
            "ticket": r.get("Ticket"),
            "deadline": r.get("Deadline"),
            "status": r.get("Status"),
            "created_at": r.get("Created At"),
        })
    return result


def mark_done(task_id: int) -> bool:
    sheet = _get_sheet()
    rows = sheet.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if row and str(row[0]) == str(task_id):
            status_col = HEADERS.index("Status") + 1
            sheet.update_cell(i, status_col, "done")
            return True
    return False
