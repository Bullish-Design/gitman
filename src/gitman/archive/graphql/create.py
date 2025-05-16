#!/usr/bin/env uv script
# @package: githubkit pydantic

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional

import githubkit
from pydantic import BaseModel, Field

from ..config import GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO, DATABASE_URL


class DiscussionCategory(BaseModel):
    id: str
    name: str
    emoji: Optional[str] = None


class DiscussionCategoriesResponse(BaseModel):
    repository: Dict[str, Any]

    @property
    def categories(self) -> List[DiscussionCategory]:
        return [
            DiscussionCategory.model_validate(node)
            for node in self.repository["discussionCategories"]["nodes"]
        ]


class DiscussionResponse(BaseModel):
    create_discussion: Dict[str, Any] = Field(alias="createDiscussion")

    @property
    def discussion_id(self) -> str:
        return self.create_discussion["discussion"]["id"]

    @property
    def discussion_url(self) -> str:
        return self.create_discussion["discussion"]["url"]


class CommentResponse(BaseModel):
    add_discussion_comment: Dict[str, Any] = Field(alias="addDiscussionComment")

    @property
    def comment_id(self) -> str:
        return self.add_discussion_comment["comment"]["id"]

    @property
    def comment_url(self) -> str:
        return self.add_discussion_comment["comment"]["url"]


class GitHubClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("GitHub token is required")

        self.client = githubkit.GitHub(self.token)

    def graphql(self, query: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
        return self.client.graphql(query, variables=variables or {})

    def get_repo_id(self, owner: str, repo: str) -> str:
        query = """
        query GetRepoID($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            id
          }
        }
        """

        variables = {"owner": owner, "name": repo}

        response = self.graphql(query, variables)
        return response["repository"]["id"]


class DiscussionsCreator:
    def __init__(self, client: GitHubClient):
        self.client = client

    def get_category_id(self, owner: str, repo: str, category_name: str) -> str:
        query = """
        query GetDiscussionCategories($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            discussionCategories(first: 50) {
              nodes {
                id
                name
              }
            }
          }
        }
        """

        variables = {"owner": owner, "name": repo}

        response = self.client.graphql(query, variables)
        parsed = DiscussionCategoriesResponse.model_validate(response)

        for category in parsed.categories:
            if category.name.lower() == category_name.lower():
                return category.id

        raise ValueError(f"Discussion category '{category_name}' not found")

    def create_discussion(
        self, owner: str, repo: str, category_id: str, title: str, body: str
    ) -> DiscussionResponse:
        repo_id = self.client.get_repo_id(owner, repo)

        mutation = """
        mutation CreateDiscussion(
          $repositoryId: ID!,
          $categoryId: ID!,
          $title: String!,
          $body: String!
        ) {
          createDiscussion(input: {
            repositoryId: $repositoryId,
            categoryId: $categoryId,
            title: $title,
            body: $body
          }) {
            discussion {
              id
              url
            }
          }
        }
        """

        variables = {
            "repositoryId": repo_id,
            "categoryId": category_id,
            "title": title,
            "body": body,
        }

        response = self.client.graphql(mutation, variables)
        return DiscussionResponse.model_validate(response)

    def add_comment(self, discussion_id: str, body: str) -> CommentResponse:
        mutation = """
        mutation AddComment($discussionId: ID!, $body: String!) {
          addDiscussionComment(input: {
            discussionId: $discussionId,
            body: $body
          }) {
            comment {
              id
              url
            }
          }
        }
        """

        variables = {"discussionId": discussion_id, "body": body}

        response = self.client.graphql(mutation, variables)
        return CommentResponse.model_validate(response)


def main():
    # parser = argparse.ArgumentParser(description="Create GitHub Discussion and Comment")
    # parser.add_argument("owner", help="Repository owner")
    # parser.add_argument("repo", help="Repository name")
    # parser.add_argument("category", help="Discussion category name")
    # parser.add_argument("title", help="Discussion title")
    # parser.add_argument("body", help="Discussion body")
    # parser.add_argument("comment", help="Comment text")
    # parser.add_argument("--token", help="GitHub token (or use GITHUB_TOKEN env var)")
    # args = parser.parse_args()

    try:
        client = GitHubClient(token=GITHUB_TOKEN)
        creator = DiscussionsCreator(client)
        category = "General"
        title = "Test Discussion"
        body = "This is a test discussion body."
        comment = "This is a test comment."

        # Get category ID
        category_id = creator.get_category_id(GITHUB_OWNER, GITHUB_REPO, category)

        # Create discussion
        discussion_result = creator.create_discussion(
            GITHUB_OWNER, GITHUB_REPO, category_id, title, body
        )

        print(f"Created discussion: {discussion_result.discussion_url}")

        # Add comment
        comment_result = creator.add_comment(discussion_result.discussion_id, comment)

        print(f"Added comment: {comment_result.comment_url}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
