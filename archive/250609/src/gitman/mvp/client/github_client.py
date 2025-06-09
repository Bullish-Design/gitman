import typer
from pprint import pprint as pp
from typing import List
from githubkit import GitHub
from githubkit.exception import RequestError
from ..models.models_base import (
    IssueSchema,
    RepositorySchema,
    UserSchema,
    CommentSchema,
)
from ...config import GITHUB_TOKEN, GITHUB_OWNER


class GitHubClient:
    def __init__(self, token: str, owner: str | None = None):
        self.owner = owner or GITHUB_OWNER
        self.client = GitHub(token)

    def fetch_repos(self, include_private: bool = True) -> List[RepositorySchema]:
        """Return repositories for *user_login*.

        * Public repos are always returned.
        * Private repos are only available when:
            - *include_private* is True **and**
            - *user_login* matches the account of this auth token (**self.owner**).
        """
        user_login = self.owner

        if include_private and user_login == self.owner:
            resp = self.client.rest.repos.list_for_authenticated_user(
                visibility="all", per_page=100
            )
        else:
            resp = self.client.rest.repos.list_for_user(
                username=user_login, per_page=100
            )
        print(f"\n\nGitHub Repos: {type(resp.parsed_data)}\n")
        # pp(resp.parsed_data)
        repos: List[RepositorySchema] = []

        for i, r in enumerate(resp.parsed_data):
            print(f"\n{i}: {r.name} - {type(r).__name__} - {r.description}\n")
            owner_payload = r.owner
            owner_schema = UserSchema.parse_obj(owner_payload)
            repo_schema = RepositorySchema.parse_obj(
                {**r.model_dump(), "owner": owner_schema}
            )
            repos.append(repo_schema)
            pp(repo_schema.model_dump())

        print(f"\n\n{type(resp.parsed_data)}\n")
        return repos  # [i.name for i in resp.parsed_data]

    def fetch_issues(self, repo: str) -> list[IssueSchema]:
        """Return a list of IssueSchema for *repo*."""
        resp = self.client.rest.issues.list_for_repo(owner=self.owner, repo=repo)

        return [
            IssueSchema(
                github_id=i.id,
                repo=repo,
                title=i.title,
                body=(i.body or ""),
            )
            for i in resp.parsed_data
        ]

    def create_issue(self, repo: str, title: str, body: str) -> IssueSchema:
        """Create an issue and return the unified schema instance."""
        resp = self.client.rest.issues.create(
            owner=self.owner, repo=repo, title=title, body=body
        )
        i = resp.parsed_data

        return IssueSchema(
            github_id=i.id, repo=repo, title=i.title, body=i.body or body
        )

    def fetch_comments(self, repo: str, issue_number: int) -> List[CommentSchema]:
        try:
            resp = self.client.rest.issues.list_comments(
                owner=self.owner, repo=repo, issue_number=issue_number, per_page=100
            )
            typer.echo(f"\n\nFetching comments for {repo}#{issue_number} …")
            typer.echo(f"\n{resp.parsed_data}")
        except RequestError as exc:
            if exc.response.status_code in {403, 404}:
                return []
            raise
        return [
            CommentSchema(
                github_id=c.id,
                issue_id=issue_number,
                repo=repo,
                author_login=c.user.login,
                body=c.body or "",
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in resp.parsed_data
        ]

    def create_comment(self, repo: str, issue_number: int, body: str) -> CommentSchema:
        resp = self.client.rest.issues.create_comment(
            owner=self.owner, repo=repo, issue_number=issue_number, body=body
        )
        c = resp.parsed_data
        return CommentSchema(
            github_id=c.id,
            issue_id=issue_number,
            repo=repo,
            author_login=c.user.login,
            body=c.body or body,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
