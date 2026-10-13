import json
import os

import requests


# monday.com GraphQL API-Version. Current (production default) as of 2026-09:
# https://developer.monday.com/api-reference/docs/api-versioning
# 2026-10 / 2027-01 are release candidates — do not use in production.
DEFAULT_MONDAY_API_VERSION = "2026-07"


class MondayClient:
    """
    monday.com GraphQL v2 client.

    API version defaults to ``2026-07`` (Monday Current / production). Override with env
    ``MONDAY_API_VERSION`` or pass ``api_version=`` for tests.
    """

    def __init__(self, api_key, api_version: str | None = None):
        self.api_key = api_key
        self.api_version = (
            api_version or os.getenv("MONDAY_API_VERSION", DEFAULT_MONDAY_API_VERSION)
        ).strip()
        # Use v2 API URL
        self.api_url = "https://api.monday.com/v2"
        # Standard headers for Monday API
        self.headers = {
            "Authorization": self.api_key,
            "API-Version": self.api_version,
            "Content-Type": "application/json",
        }

    def execute_query(self, query, variables=None):
        data = {"query": query}
        if variables is not None:
            data["variables"] = variables
        try:
            response = requests.post(self.api_url, headers=self.headers, json=data)
            
            # rate limit handling could go here (429) but keeping simple for now
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Monday API Error {response.status_code}: {response.text}")
                return None
        except Exception as e:
            print(f"Request failed: {e}")
            return None

    def create_item(
        self,
        board_id,
        group_id,
        item_name,
        column_values,
        *,
        create_labels_if_missing: bool = False,
    ):
        query = """
        mutation (
            $boardId: ID!,
            $groupId: String,
            $itemName: String!,
            $columnValues: JSON!,
            $createLabelsIfMissing: Boolean
        ) {
            create_item (
                board_id: $boardId,
                group_id: $groupId,
                item_name: $itemName,
                column_values: $columnValues,
                create_labels_if_missing: $createLabelsIfMissing
            ) {
                id
            }
        }
        """
        variables = {
            "boardId": int(board_id),
            "groupId": group_id,
            "itemName": item_name,
            "columnValues": json.dumps(column_values),
            "createLabelsIfMissing": bool(create_labels_if_missing),
        }
        return self.execute_query(query, variables)

    def update_item_columns(self, board_id, item_id, column_values):
        query = """
        mutation ($boardId: ID!, $itemId: ID!, $columnValues: JSON!) {
            change_multiple_column_values(board_id: $boardId, item_id: $itemId, column_values: $columnValues) {
                id
            }
        }
        """
        variables = {
            "boardId": int(board_id),
            "itemId": int(item_id),
            "columnValues": json.dumps(column_values)
        }
        return self.execute_query(query, variables)

    def move_item_to_group(self, item_id, group_id: str) -> dict | None:
        """Move a board item to another group (pipeline swimlane)."""
        if not group_id:
            return None
        query = """
        mutation ($itemId: ID!, $groupId: String!) {
            move_item_to_group (item_id: $itemId, group_id: $groupId) {
                id
            }
        }
        """
        variables = {"itemId": int(item_id), "groupId": str(group_id)}
        return self.execute_query(query, variables)

    def delete_item(self, item_id):
        """Permanently delete a single board item."""
        query = """
        mutation ($itemId: ID!) {
            delete_item (item_id: $itemId) {
                id
            }
        }
        """
        variables = {"itemId": int(item_id)}
        return self.execute_query(query, variables)

    def get_board_items_with_columns(self, board_id, limit=500):
        """Fetch all items from a board with group and column values using cursor pagination."""
        all_items = []
        cursor = None

        while True:
            if cursor:
                query = """
                query ($cursor: String!, $limit: Int!) {
                    next_items_page (cursor: $cursor, limit: $limit) {
                        cursor
                        items {
                            id
                            name
                            group {
                                id
                                title
                            }
                            column_values {
                                id
                                text
                                value
                            }
                        }
                    }
                }
                """
                variables = {"cursor": cursor, "limit": limit}
                data = self.execute_query(query, variables)
                if not data or not data.get("data"):
                    break
                page = data["data"].get("next_items_page")
            else:
                query = """
                query ($boardId: ID!, $limit: Int!) {
                    boards (ids: [$boardId]) {
                        items_page (limit: $limit) {
                            cursor
                            items {
                                id
                                name
                                group {
                                    id
                                    title
                                }
                                column_values {
                                    id
                                    text
                                    value
                                }
                            }
                        }
                    }
                }
                """
                variables = {"boardId": int(board_id), "limit": limit}
                data = self.execute_query(query, variables)
                if not data or not data.get("data") or not data["data"].get("boards"):
                    break
                page = data["data"]["boards"][0].get("items_page")

            if not page:
                break

            items = page.get("items", [])
            all_items.extend(items)
            cursor = page.get("cursor")
            if not cursor:
                break

        return all_items

    def get_account_slug(self) -> str | None:
        """Workspace slug for building board URLs (e.g. https://{slug}.monday.com/boards/...)."""
        data = self.execute_query("query { me { account { slug } } }")
        if not data or not data.get("data"):
            return None
        me = data["data"].get("me") or {}
        acct = me.get("account") or {}
        return (acct.get("slug") or "").strip() or None

    def get_board_metadata(self, board_id: int) -> dict | None:
        """
        Board name, groups, and columns (including settings_str for labels).

        Cleanup reports read ``name``. The engine uses groups and columns to check
        the board contract before a live push.
        """
        query = """
        query ($id: [ID!]) {
          boards(ids: $id) {
            name
            groups { id title }
            columns { id title type settings_str }
          }
        }
        """
        data = self.execute_query(query, {"id": [int(board_id)]})
        if not data or not data.get("data"):
            return None
        boards = data["data"].get("boards") or []
        if not boards:
            return None
        return boards[0]

