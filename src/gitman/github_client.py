"""GitHub API client for fetching issues, discussions, and comments."""

import os
import time
from typing import Any, Optional
from datetime import datetime

import requests
from rich.console import Console

console = Console()


class GitHubClient:
    """Client for interacting with GitHub REST and GraphQL APIs."""

    BASE_URL = "https://api.github.com"
    GRAPHQL_URL = "https://api.github.com/graphql"

    def __init__(self, token: Optional[str] = None):
        """Initialize GitHub client with authentication token.

        Args:
            token: GitHub Personal Access Token. If not provided, reads from GITHUB_TOKEN env var.
        """
        self.token = token or os.getenv("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("GitHub token required. Set GITHUB_TOKEN env var or pass token parameter.")

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _handle_rate_limit(self, response: requests.Response) -> None:
        """Handle GitHub API rate limiting."""
        if response.status_code == 403 and "rate limit" in response.text.lower():
            reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
            if reset_time:
                wait_time = reset_time - int(time.time())
                if wait_time > 0:
                    console.print(f"[yellow]Rate limited. Waiting {wait_time}s...[/yellow]")
                    time.sleep(wait_time + 1)

    def _paginate(self, url: str, params: Optional[dict] = None) -> list[dict[str, Any]]:
        """Fetch all pages of results from a paginated endpoint.

        Args:
            url: API endpoint URL
            params: Query parameters

        Returns:
            List of all items from all pages
        """
        items = []
        params = params or {}
        params.setdefault("per_page", 100)

        while url:
            response = self.session.get(url, params=params)
            self._handle_rate_limit(response)
            response.raise_for_status()

            data = response.json()
            if isinstance(data, list):
                items.extend(data)
            else:
                # Some endpoints return {items: [...]}
                items.extend(data.get("items", [data]))

            # Get next page URL from Link header
            url = None
            if "Link" in response.headers:
                links = response.headers["Link"].split(",")
                for link in links:
                    if 'rel="next"' in link:
                        url = link[link.index("<") + 1:link.index(">")]
                        params = None  # URL already contains params
                        break

        return items

    def get_repository_info(self, owner: str, repo: str) -> dict[str, Any]:
        """Get repository information.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            Repository data
        """
        url = f"{self.BASE_URL}/repos/{owner}/{repo}"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def get_issues(
        self,
        owner: str,
        repo: str,
        state: str = "all",
        since: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Fetch issues for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            state: Issue state filter (open, closed, all). Default: all
            since: Only issues updated after this time (ISO 8601 format)

        Returns:
            List of issue data
        """
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/issues"
        params = {"state": state}
        if since:
            params["since"] = since

        # Note: This endpoint returns both issues and PRs
        # We filter out PRs (they have a "pull_request" key)
        all_items = self._paginate(url, params)
        issues = [item for item in all_items if "pull_request" not in item]

        console.print(f"[green]Fetched {len(issues)} issues from {owner}/{repo}[/green]")
        return issues

    def get_issue_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        since: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Fetch comments for a specific issue.

        Args:
            owner: Repository owner
            repo: Repository name
            issue_number: Issue number
            since: Only comments updated after this time (ISO 8601 format)

        Returns:
            List of comment data
        """
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/issues/{issue_number}/comments"
        params = {}
        if since:
            params["since"] = since

        comments = self._paginate(url, params)
        return comments

    def get_all_issue_comments(
        self,
        owner: str,
        repo: str,
        since: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Fetch all issue comments for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            since: Only comments updated after this time (ISO 8601 format)

        Returns:
            List of comment data with issue association
        """
        url = f"{self.BASE_URL}/repos/{owner}/{repo}/issues/comments"
        params = {}
        if since:
            params["since"] = since

        comments = self._paginate(url, params)
        console.print(f"[green]Fetched {len(comments)} issue comments from {owner}/{repo}[/green]")
        return comments

    def get_discussions(self, owner: str, repo: str) -> list[dict[str, Any]]:
        """Fetch discussions for a repository using GraphQL API.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            List of discussion data
        """
        query = """
        query($owner: String!, $repo: String!, $cursor: String) {
          repository(owner: $owner, name: $repo) {
            discussions(first: 100, after: $cursor) {
              pageInfo {
                hasNextPage
                endCursor
              }
              nodes {
                id
                number
                title
                body
                bodyText
                createdAt
                updatedAt
                closedAt
                locked
                url
                author {
                  login
                  ... on User {
                    id
                  }
                }
                category {
                  id
                  name
                  description
                  emoji
                }
                labels(first: 10) {
                  nodes {
                    id
                    name
                    color
                  }
                }
                upvoteCount
                answerChosenAt
                answer {
                  id
                }
              }
            }
          }
        }
        """

        discussions = []
        cursor = None

        while True:
            variables = {"owner": owner, "repo": repo, "cursor": cursor}
            response = self.session.post(
                self.GRAPHQL_URL,
                json={"query": query, "variables": variables}
            )
            response.raise_for_status()

            data = response.json()
            if "errors" in data:
                raise Exception(f"GraphQL errors: {data['errors']}")

            repo_data = data["data"]["repository"]
            if not repo_data:
                console.print(f"[yellow]Repository {owner}/{repo} not found or discussions disabled[/yellow]")
                break

            discussions_data = repo_data["discussions"]
            discussions.extend(discussions_data["nodes"])

            if not discussions_data["pageInfo"]["hasNextPage"]:
                break
            cursor = discussions_data["pageInfo"]["endCursor"]

        console.print(f"[green]Fetched {len(discussions)} discussions from {owner}/{repo}[/green]")
        return discussions

    def get_discussion_comments(
        self,
        owner: str,
        repo: str,
        discussion_number: int
    ) -> list[dict[str, Any]]:
        """Fetch comments for a specific discussion using GraphQL API.

        Args:
            owner: Repository owner
            repo: Repository name
            discussion_number: Discussion number

        Returns:
            List of comment data
        """
        query = """
        query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
          repository(owner: $owner, name: $repo) {
            discussion(number: $number) {
              comments(first: 100, after: $cursor) {
                pageInfo {
                  hasNextPage
                  endCursor
                }
                nodes {
                  id
                  body
                  bodyText
                  createdAt
                  updatedAt
                  author {
                    login
                    ... on User {
                      id
                    }
                  }
                  upvoteCount
                  isAnswer
                  url
                  replies(first: 10) {
                    nodes {
                      id
                      body
                      createdAt
                      author {
                        login
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """

        comments = []
        cursor = None

        while True:
            variables = {
                "owner": owner,
                "repo": repo,
                "number": discussion_number,
                "cursor": cursor
            }
            response = self.session.post(
                self.GRAPHQL_URL,
                json={"query": query, "variables": variables}
            )
            response.raise_for_status()

            data = response.json()
            if "errors" in data:
                raise Exception(f"GraphQL errors: {data['errors']}")

            discussion_data = data["data"]["repository"]["discussion"]
            if not discussion_data:
                break

            comments_data = discussion_data["comments"]
            comments.extend(comments_data["nodes"])

            if not comments_data["pageInfo"]["hasNextPage"]:
                break
            cursor = comments_data["pageInfo"]["endCursor"]

        return comments
