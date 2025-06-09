from __future__ import annotations

from pprint import pprint
from typing import List, Tuple, Optional

from .api import GitHubAPI
from .models.graphql.repos import RepoVisibility


def setup_project_repository():
    """Set up a complete project with repository, issues, and discussions."""
    # Create API client
    api = GitHubAPI.from_token()
    owner = "Bullish-Design"

    # Create repository with features enabled
    repo_name = "api-project-demo"
    repo = api.create_repo_with_features(
        repo_name, RepoVisibility.PRIVATE, enable_issues=True, enable_discussions=True
    )
    print(f"Created repository: {repo.name} (private={repo.isPrivate})")

    # Set up project and link to repository
    project_title = "API Project Demo"
    project = api.get_or_create_project(owner, project_title)
    print(f"Created project: {project.title}")

    # Add initial issues to the repository and project
    issues: List[Tuple[str, str]] = [
        ("Set up CI/CD pipeline", "Configure GitHub Actions for CI/CD."),
        ("Design database schema", "Create initial tables and relationships."),
        ("Implement authentication", "Set up OAuth with GitHub."),
    ]

    for title, body in issues:
        issue = api.create_issue_and_add_to_project(repo.id, project.id, title, body)
        print(f"Created issue #{issue.number}: {issue.title}")

        # Add a comment to the issue
        comment = api.issue_comments.add_comment(
            issue.id, f"This is a priority task for the {project_title} project."
        )
        print(f"  Added comment to issue #{issue.number}")

    # Set up discussions in the repository
    categories = api.discussions.list_categories(owner, repo_name)

    # Find the General category
    general_category = None
    for category in categories:
        if category.name == "General":
            general_category = category
            break

    if general_category:
        # Create a discussion
        discussion = api.discussions.create_discussion(
            repo.id,
            general_category.id,
            "Welcome to the project",
            "# Project Overview\n\nThis repository contains the API project.",
        )
        print(f"Created discussion: {discussion.title}")

        # Add a comment to the discussion
        comment = api.discussion_comments.add_comment(
            discussion.id, "Let's start by defining our API endpoints."
        )
        print(f"  Added comment to discussion")

    print("\nProject setup complete!")
    return repo, project


def test_issue_management():
    """Demonstrate issue management functionality."""
    api = GitHubAPI.from_token()
    owner = "Bullish-Design"
    repo_name = "api-project-demo"

    # Find the repository
    repo = api.get_repo_by_name(owner, repo_name)
    if not repo:
        print(f"Repository {owner}/{repo_name} not found.")
        return

    # List all issues
    issues = api.issues.list_issues(owner, repo_name)
    print(f"\nFound {len(issues)} issues in {repo_name}:")
    for issue in issues:
        print(f"  #{issue.number}: {issue.title} ({issue.state})")

    # Get a specific issue by number
    if issues:
        issue_number = issues[0].number
        issue = api.get_issue_by_number(owner, repo_name, issue_number)
        if issue:
            print(f"\nRetrieved issue #{issue_number}: {issue.title}")

            # Update the issue
            updated_issue = api.issues.update_issue(
                issue.id,
                title=f"[UPDATED] {issue.title}",
                body=f"{issue.body}\n\nUpdated with additional details.",
            )
            print(f"Updated issue title: {updated_issue.title}")

            # Add a comment
            comment = api.add_comment_to_issue(
                owner, repo_name, issue_number, "Progress update: work started"
            )
            print(f"Added comment to issue #{issue_number}")

            # List comments
            comments = api.issue_comments.list_comments(owner, repo_name, issue_number)
            print(f"Issue has {len(comments)} comments")

            # Close the issue
            closed_issue = api.issues.close_issue(issue.id)
            print(f"Closed issue #{issue_number}")


def test_discussions():
    """Demonstrate discussion management functionality."""
    api = GitHubAPI.from_token()
    owner = "Bullish-Design"
    repo_name = "api-project-demo"

    # List discussion categories
    categories = api.discussions.list_categories(owner, repo_name)
    print(f"\nDiscussion categories in {repo_name}:")
    for category in categories:
        print(f"  {category.emoji or '📝'} {category.name}")

    # Create a new discussion in the Q&A category if it exists
    qa_category = api.get_discussion_category_by_name(owner, repo_name, "Q&A")
    if qa_category:
        discussion = api.discussions.create_discussion(
            api.get_repo_by_name(owner, repo_name).id,
            qa_category.id,
            "API Authentication Questions",
            "What authentication method should we use for the API?",
        )
        print(f"Created Q&A discussion: {discussion.title}")

        # Add a comment
        comment = api.discussion_comments.add_comment(
            discussion.id, "I recommend using OAuth with GitHub for authentication."
        )
        print(f"Added comment to discussion")

    # List all discussions
    discussions = api.discussions.list_discussions(owner, repo_name)
    print(f"\nFound {len(discussions)} discussions in {repo_name}:")
    for discussion in discussions:
        print(f"  #{discussion.number}: {discussion.title}")


def cleanup_demo_resources(confirm: bool = True):
    """Clean up demo resources if confirm is True."""
    if not confirm:
        print("Skipping cleanup")
        return

    api = GitHubAPI.from_token()
    owner = "Bullish-Design"
    repo_name = "api-project-demo"

    # Delete the repository
    deleted = api.repos.delete_repo(owner, repo_name)
    print(f"Deleted repository: {repo_name}")

    # Find and delete the project
    projects = api.projects.list_projects(owner)
    for project in projects:
        if project.title == "API Project Demo":
            api.projects.delete_project(project.id)
            print(f"Deleted project: {project.title}")
            break


def main():
    """Run a complete demo of the GitHub API."""
    # Create resources
    repo, project = setup_project_repository()

    # Test issue management
    test_issue_management()

    # Test discussions
    test_discussions()

    # Clean up (set to False to keep resources)
    cleanup_demo_resources(confirm=False)


if __name__ == "__main__":
    main()
