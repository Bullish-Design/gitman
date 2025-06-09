# Imports
from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Any, Dict, List, Optional
from enum import Enum
# from githubkit import GitHub


from pprint import pprint as pp
# from ....archive.graphql.test import GitHubClient


# Query Strings
GET_REPOSITORIES_QUERY = """
query GetViewerRepos($first:Int=100,$after:String){
  viewer{
    repositories(
        first:$first, 
        after:$after, 
        affiliations:[OWNER,COLLABORATOR,ORGANIZATION_MEMBER]
    ){
      pageInfo{
        hasNextPage 
        endCursor
        }
      nodes{ 
        id
        name 
        owner{ login } 
        isPrivate 
        url 
        }
    }
  }
}
"""

# Mutation Strings
# 1. Create a new repository (PUBLIC, PRIVATE, or INTERNAL)
CREATE_REPOSITORY_MUTATION = """
mutation CreateRepository(
  $name: String!
  $visibility: RepositoryVisibility!
  $ownerId: ID           # optional – defaults to the authenticated user
) {
  createRepository(
    input: { name: $name, visibility: $visibility, ownerId: $ownerId }
  ) {
    repository {
      id
      name
      owner { login }
      url
      isPrivate
    }
  }
}
"""

# 2. Edit an existing repository’s settings or metadata
UPDATE_REPOSITORY_MUTATION = """
mutation UpdateRepository(
  $repositoryId: ID!
  $name: String
  $description: String
  $homepageUrl: URI
  $hasIssuesEnabled: Boolean
  $hasDiscussionsEnabled: Boolean
  $hasWikiEnabled: Boolean
) {
  updateRepository(
    input: {
      repositoryId: $repositoryId
      name: $name
      description: $description
      homepageUrl: $homepageUrl
      hasIssuesEnabled: $hasIssuesEnabled
      hasDiscussionsEnabled: $hasDiscussionsEnabled
      hasWikiEnabled: $hasWikiEnabled
    }
  ) {
    repository {
      id
      name
      description
      url
      owner { login }
      isPrivate
      hasIssuesEnabled
      hasDiscussionsEnabled
      hasWikiEnabled
    }
  }
}
"""


# Pydantic Models


class _Owner(BaseModel):
    login: str


class RepoNode(BaseModel):
    id: str
    name: str
    owner: _Owner
    isPrivate: bool
    url: str


class RepoVisibility(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    INTERNAL = "INTERNAL"


# Misc


def parse_repo_response(response: Dict[str, Any]) -> List[RepoNode]:
    """
    Parse the GitHub GraphQL response for repositories.
    """
    repos = response["viewer"]["repositories"]["nodes"]
    repos = [RepoNode.model_validate(node) for node in repos]
    return repos


# ─── RepoManager ───────────────────────────────────────────────────────────────
class RepoManager(BaseModel):
    """All repository-level interactions for the authenticated user."""

    client: Any = Field(..., exclude=True)  # GitHubClient; Any avoids forward ref
    model_config = dict(arbitrary_types_allowed=True)

    # 1. fetch / list -----------------------------------------------------------
    def list_repos(self, first: int = 100) -> List[RepoNode]:
        """Return every repository visible to the token."""
        nodes: List[RepoNode] = []
        for page in self.client.client.graphql.paginate(
            GET_REPOSITORIES_QUERY, variables={"first": first}
        ):
            page_nodes = page["viewer"]["repositories"]["nodes"]
            nodes.extend(RepoNode.model_validate(n) for n in page_nodes)
        return nodes

    # 2. create -----------------------------------------------------------------
    def create_repo(
        self,
        name: str,
        visibility: RepoVisibility = RepoVisibility.PRIVATE,
        owner_id: Optional[str] = None,
    ) -> RepoNode:
        vars_: Dict[str, Any] = {
            "name": name,
            "visibility": visibility.value,
            "ownerId": owner_id,
        }
        # strip None values
        vars_ = {k: v for k, v in vars_.items() if v is not None}
        data = self.client.graphql(CREATE_REPOSITORY_MUTATION, vars_)
        repo_json = data["createRepository"]["repository"]
        print(f"\n\nCreated Repo Node:\n")
        pp(repo_json)
        print(f"\n")
        return RepoNode.model_validate(repo_json)

    # 3. update -----------------------------------------------------------------
    def update_repo(self, repository_id: str, **updates: Any) -> RepoNode:
        vars_ = {"repositoryId": repository_id, **updates}
        print(f"\n\nUpdate Vars:\n")
        pp(vars_)
        data = self.client.graphql(UPDATE_REPOSITORY_MUTATION, vars_)
        print(f"\n\nUpdated repo:\n\n")
        pp(data)
        repo_json = data["updateRepository"]["repository"]
        print(f"\n\n")
        return RepoNode.model_validate(repo_json)

    # 4. delete ----------------------------------------------------------------
    def delete_repo(self, owner: str, repository_name: str) -> dict | None:
        """
        Permanently delete a repository by its node-ID.

        Returns the deleted repository’s basic data when GitHub can still
        show it (usually public repos). For private repos you may get `None`.
        """
        print(f"\nDeleting repo: {repository_name}")
        client = self.client.client
        result = client.rest.repos.delete(owner, repository_name)

        print(f"\nDelete Repo Response:\n")
        pp(result)

        return


def delete_repos_exact_confirm(manager: RepoManager, target: str) -> List[str]:
    """
    Prompt user for each repository whose name == `target` before deleting.

    Args:
        manager: RepoManager instance with list/delete helpers.
        target:  Exact repo name (case-sensitive) to purge.

    Returns:
        List of repository IDs that were deleted.
    """
    deleted: List[str] = []
    looping = True

    while looping:
        matches = [repo for repo in manager.list_repos() if target in repo.name]
        [print(f"    {repo.name}") for repo in matches]
        if not matches:
            break

        for repo in matches:
            prompt = (
                f"\nDelete repository '{repo.owner.login}/{repo.name}' "
                f"({repo.url})? [y/N]: "
            )
            answer = input(prompt).strip().lower()
            if answer == "y":
                manager.delete_repo(repo.owner.login, repo.name)
                deleted.append(repo.name)
                print("  ✔ deleted")
            else:
                print("  ✖ skipped")
                looping = False
                break

    print(f"\nDone. Removed {len(deleted)} repositories.")
    return deleted
