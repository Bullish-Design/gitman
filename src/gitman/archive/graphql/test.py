#!/usr/bin/env uv script
# @package: githubkit pydantic

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional
from pprint import pprint as pp

import githubkit
from pydantic import BaseModel, Field
from ...config import GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO, DATABASE_URL
from ...mvp.models.graphql.repos import parse_repo_response, GET_REPOSITORIES_QUERY
# from ...mvp.models.graphql.issues import IssueSchema


class DiscussionAuthor(BaseModel):
    login: str
    url: str


class DiscussionComment(BaseModel):
    body: str
    author: DiscussionAuthor
    created_at: str = Field(alias="createdAt")


class DiscussionComments(BaseModel):
    nodes: List[DiscussionComment]


class DiscussionCategory(BaseModel):
    id: str
    name: str
    emoji: str


class Discussion(BaseModel):
    id: str
    title: str
    body: str
    url: str
    author: DiscussionAuthor
    created_at: str = Field(alias="createdAt")
    category: DiscussionCategory
    comments: DiscussionComments

    @property
    def comment_list(self) -> List[DiscussionComment]:
        return self.comments.nodes


class DiscussionsResponse(BaseModel):
    repository: Dict[str, Any]

    @property
    def discussions(self) -> List[Discussion]:
        return [
            Discussion.model_validate(node)
            for node in self.repository["discussions"]["nodes"]
        ]


class GitHubClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("GitHub token is required")

        self.client = githubkit.GitHub(self.token)

    def graphql(self, query: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
        return self.client.graphql(query, variables=variables or {})


class DiscussionsManager:
    def __init__(self, client: GitHubClient):
        self.client = client

    def get_discussions(self, owner: str, repo: str) -> List[Discussion]:
        query = """
        query GetDiscussions($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            discussions(first: 50) {
              nodes {
                id
                title
                body
                url
                createdAt
                author {
                  login
                  url
                }
                category {
                  id
                  name
                  emoji
                }
                comments(first: 10) {
                  nodes {
                    body
                    createdAt
                    author {
                      login
                      url
                    }
                  }
                }
              }
            }
          }
        }
        """

        variables = {"owner": owner, "name": repo}

        response = self.client.graphql(query, variables)
        print(f"\n\nGitHub Discussions Response:\n{response}\n\n")
        parsed = DiscussionsResponse.model_validate(response)

        return parsed.discussions


GET_REPOSITORIES_QUERY = """
query GetViewerRepos($first:Int=100,$after:String){
  viewer{
    repositories(first:$first,after:$after,affiliations:[OWNER,COLLABORATOR,ORGANIZATION_MEMBER]){
      pageInfo{hasNextPage endCursor}
      nodes{ name owner{ login } isPrivate url }
    }
  }
}
"""


class RepoManager:
    def __init__(self, client: GitHubClient):
        self.client = client

    def get_repos(self, owner: str, repo: str):  # -> List[Discussion]:
        variables = {}  # {"owner": owner, "name": repo}

        response = self.client.graphql(GET_REPOSITORIES_QUERY, variables)
        print(f"\n\nGitHub Repo Response:\n")  # "{response}\n\n")
        # parsed = DiscussionsResponse.model_validate(response)
        repos = parse_repo_response(response)
        pp(repos)
        print(f"\n\n{type(repos)}\n")  # "{response}\n\n")
        return repos  # parsed.discussions


def main():
    # if len(sys.argv) < 3:
    # parser = argparse.ArgumentParser(description="Get GitHub Discussions")
    # parser.add_argument("owner", help="Repository owner")
    # parser.add_argument("repo", help="Repository name")
    # parser.add_argument("--token", help="GitHub token (or use GITHUB_TOKEN env var)")
    # args = parser.parse_args()

    try:
        client = GitHubClient(token=GITHUB_TOKEN)
        response = RepoManager(client).get_repos(GITHUB_OWNER, GITHUB_REPO)
        # manager = DiscussionsManager(client)
        exit()
        # discussions = manager.get_discussions(GITHUB_OWNER, GITHUB_REPO)
        print(f"\n\nGitHub Discussions for {GITHUB_OWNER}/{GITHUB_REPO}:\n")
        # print(f"Found {len(discussions)} discussions:")
        print(f"\n\n{type(discussions)}:\n")
        pp(discussions, indent=4)
        # print(f"Found {len(discussions)} discussions:")
        for i, discussion in enumerate(discussions, 1):
            print(f"\n{i}. {discussion.title}")
            print(f"   by {discussion.author.login} ({discussion.created_at})")
            print(
                f"   Category: {discussion.category.name} {discussion.category.emoji}"
            )
            print(f"   URL: {discussion.url}")
            print(f"   Comments: {len(discussion.comment_list)}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
