# Imports
from typing import List
from pprint import pprint as pp


from ...archive.graphql.test import GitHubClient

from .graphql.projects import ProjectManager, ProjectNode, ProjectState
from .graphql.repos import (
    RepoManager,
    RepoNode,
    RepoVisibility,
    delete_repos_exact_confirm,
)
from .graphql.issues import IssueManager, IssueState, IssueNode
from .graphql.discussions import DiscussionManager, DiscussionNode
from .graphql.issue_comments import IssueCommentManager, IssueCommentNode
from .graphql.discussion_comments import DiscussionCommentManager, DiscussionCommentNode

# Common:
gh = GitHubClient()
OWNER = "Bullish-Design"
REPO = "demo"


# Repos:
def test_repos():
    repos = RepoManager(client=gh)

    all_repos = repos.list_repos()

    print(f"\n\nGitHub Repos:\n")
    [print(f"   {repo}") for repo in all_repos]

    new_repo = repos.create_repo(REPO, RepoVisibility.PRIVATE)

    print(f"\n\nGitHub Repo Created:\n")
    pp(new_repo)
    print(f"\n")

    patched = repos.update_repo(
        new_repo.id, hasIssuesEnabled=True, hasDiscussionsEnabled=True
    )

    print(f"\n\nGitHub Repo Patched:\n")
    pp(patched)
    print(f"\n\n")

    result = delete_repos_exact_confirm(repos, "demo")
    # deleted = repos.delete_repo(new_repo.id)
    print(f"\n\nDeleted Repo:\n\n{result}\n\n")


def test_issues(new_repo: RepoNode):
    print(f"\nTesting Issues:\n")
    issues = IssueManager(client=gh)

    new_one = issues.create_issue(new_repo.id, "Test: Testing issues api", "Steps …")
    print(f"\nNew Issue: \n")
    pp(new_one)
    print(f"\n")
    all_open = issues.list_issues(
        "Bullish-Design", new_repo.name, state=IssueState.OPEN
    )
    print(f"\nList of issues:\n\n")
    pp(all_open)
    print(f"\n")
    closed = issues.close_issue(new_one.id)
    print(f"\nClosed Issue:\n")
    pp(closed)


def test_discussions(new_repo: RepoNode):
    print(f"\nDiscussions:\n\n")
    discussions = DiscussionManager(client=gh)

    cats = discussions.list_categories(OWNER, new_repo.name)
    pp(cats)
    print(f"\n")
    cat_id = ""

    for c in cats:
        print(f"    {c.emoji or ''} {c.name:<15} – answerable={c.isAnswerable}")
        if c.name == "General":
            cat_id = c.id

    # -----------------------------------------------------------------------------
    # 3.  create one
    # -----------------------------------------------------------------------------
    print("\n\n=== Creating a new discussion:\n")
    new_disc: DiscussionNode = discussions.create_discussion(
        repository_id=new_repo.id,
        category_id=cat_id,
        title="API v2 – feedback welcome",
        body="Please share thoughts on the new endpoint.",
    )
    pp(new_disc.model_dump())

    # -----------------------------------------------------------------------------
    # 4.  update it (title + body)
    # -----------------------------------------------------------------------------
    print("\n=== Updating the discussion we just created")
    updated_disc: DiscussionNode = discussions.update_discussion(
        new_disc.id,
        title="[UPDATED] API v2 – feedback thread",
        body="### Changelog\n* Added pagination\n* Clarified errors",
    )
    pp(updated_disc)

    # -----------------------------------------------------------------------------
    # 2.  list existing discussions
    # -----------------------------------------------------------------------------
    print("\n=== Current discussions:")
    dnum = 0
    for d in discussions.list_discussions(OWNER, new_repo.name):
        print(
            f"#{d.number:<4} {d.title:<40}  "
            f"(created {d.createdAt}, updated {d.updatedAt})\n"
        )
        dnum = d.number

    return dnum


def test_discussion_comments(new_disc: DiscussionNode, new_repo: RepoNode, dnum: int):
    # gh = GitHubClient()  # PAT needs discussions:write
    c_mgr = DiscussionCommentManager(client=gh)

    # 2. add a new comment
    new_comment = c_mgr.add_comment(
        discussion_id=new_disc.id,  # "D_kwDOExampleDiscussionId",
        body="Thanks for the clarification!",
    )
    print("Added:", new_comment.id)

    # 3. update it
    updated = c_mgr.update_comment(new_comment.id, body="**EDIT:** clarity added.")
    print("Updated at:", updated.updatedAt)

    # 1. list comments on discussion 1
    comments = c_mgr.list_comments(OWNER, new_repo.name, discussion_number=dnum)
    print(f"Found {len(comments)} comments")
    print(comments[0].body, comments[0].createdAt)

    # 4. delete it
    # c_mgr.delete_comment(updated.id)
    # print("Comment removed.")

    # -----------------------------------------------------------------------------
    # 5.  delete it (cleanup)
    # -----------------------------------------------------------------------------
    # print("\n=== Deleting the discussion")
    # deleted_stub = discussions.delete_discussion(updated_disc.id)
    # pp(deleted_stub)  # GitHub echoes back {id, number, title}


def test_issue_comments(new_repo: RepoNode, new_one: IssueNode):
    cmnt = IssueCommentManager(client=gh)

    # add new comment
    new_c = cmnt.add_comment(subject_id=new_one.id, body="Thanks for the report!")

    # edit existing comment
    edited = cmnt.update_comment(new_c.id, body="Updated text")

    # list
    comments = cmnt.list_comments(OWNER, new_repo.name, issue_number=1)

    # delete
    # cmnt.delete_comment(edited.id)

    print(f"\n=== Cleanup: (if desired)\n")
    result = delete_repos_exact_confirm(repos, "demo")


def test_projects():
    gh = GitHubClient()  # PAT needs “projects:write”
    p_mgr = ProjectManager(client=gh)
    repos = RepoManager(client=gh)
    issues = IssueManager(client=gh)

    repo_name = "demo1"

    all_repos = repos.list_repos()
    repo_match = [repo for repo in all_repos if repo.name == repo_name][0]
    print(f"\nRepo: {repo_match}\n")

    new_issue = issues.create_issue(
        repo_match.id, "Test: Testing issues api", "Steps …"
    )
    print(f"\nNew Issue: \n    {new_issue}")

    all_open = issues.list_issues(OWNER, repo_match.name, state=IssueState.OPEN)
    print(f"\n\nOpen Issues: ")
    [print(f"    {issue}") for issue in all_open]

    linked_issue = all_open[0]

    # 1. list
    projects = p_mgr.list_projects(OWNER)
    print("\n\nOpen projects:", [p.title for p in projects])

    # 2. create
    new_proj = p_mgr.create_project(owner_login=OWNER, title="Automation Roadmap")
    print("\n\nCreated:", new_proj.id, new_proj.createdAt)

    # 2.5 Add issue:
    proj_issue = p_mgr.add_issue(new_proj.id, linked_issue.id)
    print(f"\n\nLinked Issue: \n{proj_issue}\n\n")

    ## 3. update (close it)
    # closed = p_mgr.update_project(
    #    new_proj.id, closed=True, short_description="Archived"
    # )
    # print("State:", closed.state, closed.updatedAt)

    ## 4. delete
    # deleted_id = p_mgr.delete_project(closed.id)
    # print("Deleted:", deleted_id)


def test_github_api():
    test_projects()


def main():
    """Main function to run the tests."""
    # test_repos()
    test_github_api()


if __name__ == "__main__":
    main()
