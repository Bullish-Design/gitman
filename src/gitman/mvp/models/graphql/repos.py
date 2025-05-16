# Imports
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from enum import Enum

from ....archive.graphql.test import GithubClient


# Query Strings
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

# Mutation Strings
# 1. Create a new repository (PUBLIC, PRIVATE, or INTERNAL)
CREATE_REPOSITORY_MUTATION = """
mutation CreateRepository(
  $name: String!
  $visibility: RepositoryVisibility!
  #$ownerId: ID           # optional – defaults to the authenticated user
) {
  createRepository(
    input: { name: $name, visibility: $visibility, ownerId: $ownerId }
  ) {
    repository {
      id
      name
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
            _GET_REPOS_Q, variables={"first": first}
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
        return RepoNode.model_validate(repo_json)

    # 3. update -----------------------------------------------------------------
    def update_repo(self, repository_id: str, **updates: Any) -> RepoNode:
        vars_ = {"repositoryId": repository_id, **updates}
        data = self.client.graphql(UPDATE_REPOSITORY_MUTATION, vars_)
        repo_json = data["updateRepository"]["repository"]
        return RepoNode.model_validate(repo_json)


def create_repository(
    self,
    name: str,
    visibility: RepoVisibility = RepoVisibility.PRIVATE,
    owner_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new repository and return the repo object."""
    vars_ = {
        "name": name,
        "visibility": visibility.value,
        "ownerId": owner_id,
    }
    # remove None values so we don't send them
    vars_ = {k: v for k, v in vars_.items() if v is not None}
    data = self.graphql(CREATE_REPOSITORY_MUTATION, vars_)
    return data["createRepository"]["repository"]


def update_repository(
    self,
    repository_id: str,
    **updates: Any,
) -> Dict[str, Any]:
    """
    Update repo metadata. Pass any combination of:
      name, description, homepageUrl,
      hasIssuesEnabled, hasDiscussionsEnabled, hasWikiEnabled
    """
    vars_ = {"repositoryId": repository_id, **updates}
    data = self.graphql(UPDATE_REPOSITORY_MUTATION, vars_)
    return data["updateRepository"]["repository"]
