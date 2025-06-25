#!/usr/bin/env python
"""HTTP client for GitHub API with retry logic."""

from __future__ import annotations
import time
import logging
from typing import Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import get_config
from .models import *

logger = logging.getLogger("gitman.client")


class GitHubClient:
    """GitHub API client with retry and rate limiting."""

    def __init__(self) -> None:
        self.config = get_config()
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create requests session with retry strategy."""
        session = requests.Session()

        # Retry strategy for connection/timeout errors
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.retry_backoff,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Set headers
        session.headers.update(
            {
                "Authorization": f"Bearer {self.config.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "gitman",
            }
        )

        return session

    def _request(self, method: str, endpoint: str, **kwargs) -> dict[str, Any]:
        """Make API request with error handling."""
        url = f"{self.config.base_url}{endpoint}"

        try:
            response = self.session.request(
                method, url, timeout=self.config.timeout, **kwargs
            )

            # Handle rate limiting
            if response.status_code == 429:
                reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
                sleep_time = max(reset_time - int(time.time()), 60)
                logger.warning(f"Rate limited. Sleeping {sleep_time}s")
                time.sleep(sleep_time)
                return self._request(method, endpoint, **kwargs)

            response.raise_for_status()
            return response.json()

        except requests.RequestException as e:
            logger.error(f"API request failed: {e}")
            raise

    def get(self, endpoint: str, **kwargs) -> dict[str, Any]:
        """GET request."""
        return self._request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs) -> dict[str, Any]:
        """POST request."""
        return self._request("POST", endpoint, **kwargs)

    def patch(self, endpoint: str, **kwargs) -> dict[str, Any]:
        """PATCH request."""
        return self._request("PATCH", endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs) -> dict[str, Any]:
        """DELETE request."""
        return self._request("DELETE", endpoint, **kwargs)


class ProjectsGraphQLClient:
    """GitHub GraphQL client for Projects v2."""

    def __init__(self) -> None:
        self.config = get_config()
        self.url = "https://api.github.com/graphql"
        self.headers = {
            "Authorization": f"Bearer {self.config.github_token}",
            "Content-Type": "application/json",
        }

    def query(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute GraphQL query."""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = requests.post(
                self.url,
                json=payload,
                headers=self.headers,
                timeout=self.config.timeout,
            )
            response.raise_for_status()

            data = response.json()
            if "errors" in data:
                raise Exception(f"GraphQL errors: {data['errors']}")

            return data["data"]

        except requests.RequestException as e:
            logger.error(f"GraphQL request failed: {e}")
            raise

    def get_viewer_login(self) -> str:
        """Get authenticated user's login."""
        query = "query { viewer { login } }"
        result = self.query(query)
        return result["viewer"]["login"]

    def create_project(
        self, owner: str, title: str, readme: str = ""
    ) -> dict[str, Any]:
        """Create a new project."""
        mutation = """
        mutation CreateProject($ownerId: ID!, $title: String!) {
          createProjectV2(input: {
            ownerId: $ownerId
            title: $title
          }) {
            projectV2 {
              id
              number
              title
              readme
              url
              closed
              createdAt
              updatedAt
              owner {
                ... on User { login }
                ... on Organization { login }
              }
            }
          }
        }
        """

        # Get owner ID first
        owner_id = self._get_owner_id(owner)

        variables = {"ownerId": owner_id, "title": title} #, "readme": readme}

        result = self.query(mutation, variables)
        return result["createProjectV2"]["projectV2"]

    def add_item_to_project(self, project_id: str, content_id: str) -> dict[str, Any]:
        """Add issue/PR to project."""
        mutation = """
        mutation AddProjectItem($projectId: ID!, $contentId: ID!) {
          addProjectV2ItemById(input: {
            projectId: $projectId
            contentId: $contentId
          }) {
            item {
              id
              createdAt
              updatedAt
              content {
                ... on Issue { 
                  number
                  title
                  url
                }
                ... on PullRequest {
                  number  
                  title
                  url
                }
              }
            }
          }
        }
        """

        variables = {"projectId": project_id, "contentId": content_id}
        result = self.query(mutation, variables)
        return result["addProjectV2ItemById"]["item"]

    def _get_owner_id(self, owner: str) -> str:
        """Get owner node ID."""
        # Try user first
        user_query = """
        query GetUser($login: String!) {
          user(login: $login) { id }
        }
        """
        
        try:
            result = self.query(user_query, {"login": owner})
            if result.get("user", {}).get("id"):
                return result["user"]["id"]
        except:
            pass
        
        # Try organization
        org_query = """
        query GetOrg($login: String!) {
          organization(login: $login) { id }
        }
        """
        
        result = self.query(org_query, {"login": owner})
        if result.get("organization", {}).get("id"):
            return result["organization"]["id"]
            
        raise ValueError(f"Could not find user or organization: {owner}")
