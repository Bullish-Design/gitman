# Imports
from pydantic import BaseModel
from typing import Any, Dict, List

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


# Pydantic Models


class _Owner(BaseModel):
    login: str


class RepoNode(BaseModel):
    name: str
    owner: _Owner
    isPrivate: bool
    url: str


def parse_repo_response(response: Dict[str, Any]) -> List[RepoNode]:
    """
    Parse the GitHub GraphQL response for repositories.
    """
    repos = response["viewer"]["repositories"]["nodes"]
    repos = [RepoNode.model_validate(node) for node in repos]
    return repos


# Misc
