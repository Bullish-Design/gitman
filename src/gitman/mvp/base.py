import typer
import asyncio
import pprint as pp
from .db.db_base import SessionLocal, Issue, Repository, User, Comment
from .client.github_client import GitHubClient
from ..config import GITHUB_TOKEN
from typing import List, Optional


app = typer.Typer()
github = GitHubClient(GITHUB_TOKEN)


@app.command(
    name="fetch-all-comments",
    help="Sync *all* comments from *all* repositories you own.",
)
def fetch_all_comments():
    """Iterate over every repo → every issue → every comment and cache them."""
    db = SessionLocal()

    repos = github.fetch_repos(include_private=True)
    total_comments = 0
    for r in repos:
        typer.echo(f"◼ Repo: {r.name}")
        issues = github.fetch_issues(r.name)
        for iss in issues:
            schemas = github.fetch_comments(r.name, iss.github_id)
            typer.echo(f"  • Issue Comment Response: {schemas}")
            for c in schemas:
                row = db.query(Comment).filter(Comment.github_id == c.github_id).first()
                if row:
                    row.body = c.body
                    row.updated_at = c.updated_at
                else:
                    db.add(Comment(**c.dict()))
            db.commit()
            typer.echo(f"    • {len(schemas):2} comment(s) for issue {iss.github_id}")
            total_comments += len(schemas)
    db.close()
    typer.echo(
        f"Fetched {total_comments} total comment(s) across {len(repos)} repo(s)."
    )


@app.command(help="Sync comments for an issue or for *all* issues in a repo.")
def fetch_comments(
    repo: str = typer.Argument(..., help="Repository name"),
    issue_number: Optional[int] = typer.Argument(
        None, help="Issue number (omit with --all)"
    ),
    all: bool = typer.Option(
        False,
        "--all",
        help="Fetch comments from *all* issues in the given repository.",
    ),
):
    if not all and issue_number is None:
        typer.secho("Error: Provide <issue_number> or use --all", fg=typer.colors.RED)
        raise typer.Exit(1)

    db = SessionLocal()

    issue_numbers: List[int]
    if all:
        # ensure local issue cache is up‑to‑date for this repo
        local_issues = github.fetch_issues(repo)
        issue_numbers = [i.github_id for i in local_issues]
    else:
        issue_numbers = [issue_number]

    total = 0
    for num in issue_numbers:
        typer.echo(f"Fetching comments for {repo}#{num} …")
        schemas = github.fetch_comments(repo, num)
        for c in schemas:
            row = db.query(Comment).filter(Comment.github_id == c.github_id).first()
            if row:
                row.body = c.body
                row.updated_at = c.updated_at
            else:
                db.add(Comment(**c.dict()))
        db.commit()
        typer.echo(f"  ✓ {len(schemas):2} comment(s) cached")
        total += len(schemas)

    db.close()
    typer.echo(f"Fetched {total} comment(s) from {len(issue_numbers)} issue(s).")


@app.command(help="Create a comment on GitHub and cache it locally.")
def create_comment(
    repo: str = typer.Argument(..., help="Repository name"),
    issue_number: int = typer.Argument(..., help="Issue number"),
    body: str = typer.Argument(..., help="Comment body text"),
):
    # GitHub API call
    c_schema = github.create_comment(repo, issue_number, body)

    # cache locally
    db = SessionLocal()
    db.add(Comment(**c_schema.dict()))
    db.commit()
    db.close()

    typer.echo(f"✅ Comment created on {repo}#{issue_number} and cached.")


@app.command()
def fetch_repos(
    private: bool = typer.Option(
        True,
        "--private/--no-private",
        help="Include private repositories (only works when *user* matches the authenticated account)",
    ),
):
    """Pull repositories for *user* (public plus optional private) and save to DB."""
    db = SessionLocal()
    schemas = github.fetch_repos(include_private=private)

    new_repo_count = 0
    updated_repo_count = 0

    for repo_schema in schemas:
        # upsert owner first
        urow = (
            db.query(User).filter(User.github_id == repo_schema.owner.github_id).first()
        )
        if urow:
            # quick update
            urow.login = repo_schema.owner.login
            urow.avatar_url = str(repo_schema.owner.avatar_url)
            urow.html_url = str(repo_schema.owner.html_url)
        else:
            db.add(
                User(
                    github_id=repo_schema.owner.github_id,
                    node_id=repo_schema.owner.node_id,
                    login=repo_schema.owner.login,
                    name=repo_schema.owner.name,
                    email=repo_schema.owner.email,
                    avatar_url=str(repo_schema.owner.avatar_url),
                    html_url=str(repo_schema.owner.html_url),
                    type=repo_schema.owner.type,
                    site_admin=repo_schema.owner.site_admin,
                )
            )

        # upsert repo
        rrow = (
            db.query(Repository)
            .filter(Repository.github_id == repo_schema.github_id)
            .first()
        )
        if rrow:
            updated_repo_count += 1
            rrow.name = repo_schema.name
            rrow.full_name = repo_schema.full_name
            rrow.owner_login = repo_schema.owner.login
            rrow.private = repo_schema.private
            rrow.description = repo_schema.description
            rrow.html_url = str(repo_schema.html_url)
            rrow.default_branch = repo_schema.default_branch
            rrow.visibility = repo_schema.visibility
            rrow.language = repo_schema.language
            rrow.stargazers_count = repo_schema.stargazers_count
            rrow.forks_count = repo_schema.forks_count
            rrow.open_issues_count = repo_schema.open_issues_count
            rrow.pushed_at = repo_schema.pushed_at
            rrow.created_at = repo_schema.created_at
            rrow.updated_at = repo_schema.updated_at
            rrow.archived = repo_schema.archived
            rrow.disabled = repo_schema.disabled
        else:
            new_repo_count += 1
            db.add(
                Repository(
                    github_id=repo_schema.github_id,
                    node_id=repo_schema.node_id,
                    name=repo_schema.name,
                    full_name=repo_schema.full_name,
                    owner_login=repo_schema.owner.login,
                    private=repo_schema.private,
                    description=repo_schema.description,
                    html_url=str(repo_schema.html_url),
                    default_branch=repo_schema.default_branch,
                    visibility=repo_schema.visibility,
                    language=repo_schema.language,
                    stargazers_count=repo_schema.stargazers_count,
                    forks_count=repo_schema.forks_count,
                    open_issues_count=repo_schema.open_issues_count,
                    pushed_at=repo_schema.pushed_at,
                    created_at=repo_schema.created_at,
                    updated_at=repo_schema.updated_at,
                    archived=repo_schema.archived,
                    disabled=repo_schema.disabled,
                )
            )

    db.commit()
    db.close()

    typer.echo(
        f"Synced {len(schemas)} repos for user → DB  (new: {new_repo_count}, updated: {updated_repo_count})"
    )


@app.command()
def fetch_issues(
    repo: str = typer.Argument(
        None, help="Single repository name (omit when using --all)"
    ),
    all: bool = typer.Option(
        False,
        "--all",
        help="Fetch issues from *all* repositories owned by the authenticated account (public + private).",
    ),
):
    """Sync GitHub issues into the local DB.

    • If *repo* is provided, only that repository is synced.
    • If `--all` is passed, the command will enumerate every repository owned by the
      authenticated user (including private) and pull their issues one‑by‑one.
    """

    if not all and not repo:
        typer.echo(
            "Error: Provide a <repo> argument or use --all"
        )  # , fg=typer.colors.RED)
        raise typer.Exit(1)

    # Determine which repositories to process ----------------------
    repo_names: List[str]
    if all:
        repo_schemas = github.fetch_repos(include_private=True)
        repo_names = [r.name for r in repo_schemas]
    else:
        repo_names = [repo]

    db = SessionLocal()
    total_issues = 0

    for rname in repo_names:
        typer.echo(f"Fetching issues for {rname}...")
        try:
            schemas = github.fetch_issues(rname)
        except:
            typer.echo(
                f"    ✗ Failed to fetch issues for {rname} (repo not found?)",
                # fg=typer.colors.RED,
            )
            continue
        for s in schemas:
            row = db.query(Issue).filter(Issue.github_id == s.github_id).first()
            if row:
                row.title = s.title
                row.body = s.body
            else:
                db.add(Issue(**s.dict()))
        total_issues += len(schemas)
        db.commit()
        typer.echo(f"    ✓ {len(schemas):3} issue(s) synced for {rname}")

    db.close()
    typer.echo(
        f"Fetched {total_issues} issue(s) across {len(repo_names)} repository/ies → DB."
    )
    typer.echo(f"Fetched {len(schemas)} issues from {repo} → DB.")


@app.command()
def list_issues(repo: str):
    db = SessionLocal()
    issues = db.query(Issue).filter(Issue.repo == repo).all()
    for issue in issues:
        typer.echo(f"\n{issue.github_id}: {issue.title}")
    db.close()


@app.command()
def create_issue(repo: str, title: str, body: str):
    issue_schema = asyncio.run(github.create_issue(repo, title, body))

    db = SessionLocal()
    issue = Issue(**issue_schema.dict())
    db.add(issue)
    db.commit()
    db.close()

    typer.echo(f"\n\nIssue '{title}' created in repo '{repo}'.\n")


def main():
    app()


if __name__ == "__main__":
    main()
