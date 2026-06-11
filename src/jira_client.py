"""
jira_client.py — Read-only Jira REST v3 wrapper for FLIPPI project.

All methods are READ-ONLY. No create/edit/transition/comment calls here.
Reference: Jira REST API Reference doc (verified against flipkart.atlassian.net, 2026-06-10)
"""

import os
import time
import requests
from requests.auth import HTTPBasicAuth
from typing import Optional


class JiraClient:
    def __init__(self):
        email = os.environ["JIRA_EMAIL"]
        token = os.environ["JIRA_TOKEN"]
        self.base_url = os.environ.get("JIRA_BASE_URL", "https://flipkart.atlassian.net")
        self.project = os.environ.get("JIRA_PROJECT", "FLIPPI")
        self.auth = HTTPBasicAuth(email, token)
        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}

    def _get(self, path: str, params: dict = None) -> dict:
        """GET with retry on 429."""
        url = f"{self.base_url}{path}"
        for attempt in range(3):
            resp = requests.get(url, auth=self.auth, headers=self.headers, params=params)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 5))
                print(f"  [rate limit] sleeping {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"GET {path} failed after retries")

    def _post(self, path: str, body: dict) -> dict:
        """POST with retry on 429."""
        url = f"{self.base_url}{path}"
        for attempt in range(3):
            resp = requests.post(url, auth=self.auth, headers=self.headers, json=body)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 5))
                print(f"  [rate limit] sleeping {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"POST {path} failed after retries")

    # -------------------------------------------------------------------------
    # Auth check
    # -------------------------------------------------------------------------

    def whoami(self) -> dict:
        """Verify token and return current user info."""
        return self._get("/rest/api/3/myself")

    # -------------------------------------------------------------------------
    # Issue fetch
    # -------------------------------------------------------------------------

    def get_issue(self, key: str, expand_rendered: bool = True) -> dict:
        """
        Fetch a single issue with lean field set + optional rendered HTML.
        Returns the raw Jira issue dict.
        """
        fields = (
            "summary,description,status,assignee,reporter,priority,"
            "labels,components,comment,created,updated,issuelinks,"
            "issuetype,resolution,customfield_10331"
        )
        params = {"fields": fields}
        if expand_rendered:
            params["expand"] = "renderedFields"
        return self._get(f"/rest/api/3/issue/{key}", params=params)

    # -------------------------------------------------------------------------
    # Search / JQL
    # -------------------------------------------------------------------------

    def search(
        self,
        jql: str,
        fields: list[str] = None,
        max_issues: int = 200,
    ) -> list[dict]:
        """
        Search Jira using JQL. Returns a flat list of issue dicts (up to max_issues).
        Uses token-based pagination (nextPageToken style) per the v3 spec.
        """
        if fields is None:
            fields = [
                "summary", "description", "status", "assignee",
                "priority", "labels", "components", "created",
                "updated", "issuetype", "customfield_10331",
            ]

        issues = []
        next_token = None

        while len(issues) < max_issues:
            batch_size = min(100, max_issues - len(issues))
            body = {
                "jql": jql,
                "maxResults": batch_size,
                "fields": fields,
            }
            if next_token:
                body["nextPageToken"] = next_token

            data = self._post("/rest/api/3/search/jql", body)
            batch = data.get("issues", [])
            issues.extend(batch)

            if data.get("isLast", True) or not batch:
                break
            next_token = data.get("nextPageToken")
            time.sleep(0.2)  # be polite

        return issues[:max_issues]

    def fetch_recent_bugs(self, limit: int = 300) -> list[dict]:
        """
        Fetch recent bugs from FLIPPI for building the similarity index.
        Returns list of issue dicts with summary, description, assignee, priority.
        """
        jql = (
            f"project = {self.project} "
            f"AND issuetype = Bug "
            f"ORDER BY updated DESC"
        )
        print(f"  [jira] fetching up to {limit} recent bugs from {self.project}...")
        issues = self.search(jql, max_issues=limit)
        print(f"  [jira] fetched {len(issues)} issues")
        return issues

    def text_search_bugs(self, query: str, limit: int = 20) -> list[dict]:
        """
        Full-text search Jira for bugs matching a query string.
        Used as a fast pre-filter before vector similarity.
        """
        # Escape double quotes in query
        safe_query = query.replace('"', '\\"')
        jql = (
            f'project = {self.project} AND issuetype = Bug '
            f'AND text ~ "{safe_query}" ORDER BY updated DESC'
        )
        return self.search(jql, max_issues=limit)

    # -------------------------------------------------------------------------
    # Helpers for extracting clean text from issue fields
    # -------------------------------------------------------------------------

    @staticmethod
    def extract_text(issue: dict) -> str:
        """
        Return a single string combining summary + description text from an issue.
        Handles ADF description gracefully — falls back to rendered or raw.
        """
        fields = issue.get("fields", {})
        summary = fields.get("summary", "")

        # Try rendered HTML description first (simpler to strip than ADF)
        rendered = issue.get("renderedFields", {})
        desc_html = rendered.get("description", "")
        if desc_html:
            # Strip HTML tags crudely
            import re
            desc_text = re.sub(r"<[^>]+>", " ", desc_html).strip()
        else:
            # Parse ADF manually (extract all text nodes)
            desc_adf = fields.get("description") or {}
            desc_text = _extract_adf_text(desc_adf)

        return f"{summary}\n{desc_text}".strip()

    @staticmethod
    def extract_assignee(issue: dict) -> Optional[str]:
        """Return display name of assignee, or None."""
        assignee = issue.get("fields", {}).get("assignee")
        if assignee:
            return assignee.get("displayName") or assignee.get("emailAddress")
        return None

    @staticmethod
    def extract_priority(issue: dict) -> str:
        """Return priority name (P0–P4 or Unknown)."""
        priority = issue.get("fields", {}).get("priority")
        if priority:
            return priority.get("name", "Unknown")
        return "Unknown"


# ---------------------------------------------------------------------------
# ADF text extraction helper
# ---------------------------------------------------------------------------

def _extract_adf_text(node: dict) -> str:
    """Recursively extract all text from an ADF node."""
    if not node or not isinstance(node, dict):
        return ""
    node_type = node.get("type", "")
    if node_type == "text":
        return node.get("text", "")
    parts = []
    for child in node.get("content", []):
        parts.append(_extract_adf_text(child))
    return " ".join(p for p in parts if p)
