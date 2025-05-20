# ── std-lib ───────────────────────────────────────────────────────────────────
from enum import Enum
from typing import Any, Dict, List, Optional

# ── third-party ───────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field

# ─────────────────────────── GraphQL documents ────────────────────────────────
LIST_PROJECTS_QUERY = """
query ListProjects(
  $owner: String!
  $first: Int  = 50
  $after: String
){
  user(login: $owner) {                         # swap to organization(login:)
    projectsV2(first: $first, after: $after) {  # for org-owned projects
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        number
        title
        shortDescription
        createdAt
        updatedAt
        closed
        url
      }
    }
  }
}
"""

CREATE_PROJECT_MUTATION = """
mutation CreateProject(
  $ownerId: ID!
  $title: String!
){
  createProjectV2(input:{ ownerId: $ownerId, title: $title }) {
    projectV2 {
      id
      number
      title
      shortDescription
      createdAt
      updatedAt
      closed
      url
    }
  }
}
"""

UPDATE_PROJECT_MUTATION = """
mutation UpdateProject(
  $projectId: ID!
  $title: String
  $shortDescription: String
  $closed: Boolean
){
  updateProjectV2(
    input:{
      projectId: $projectId
      title: $title
      shortDescription: $shortDescription
      closed: $closed
    }
  ) {
    projectV2 {
      id
      number
      title
      shortDescription
      createdAt
      updatedAt
      closed
      url
    }
  }
}
"""

DELETE_PROJECT_MUTATION = """
mutation DeleteProject($projectId: ID!){
  deleteProjectV2(input:{ projectId: $projectId }) {
    deletedItemId
  }
}
"""


# ───────────────────────────── data models ────────────────────────────────────
class ProjectState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ProjectNode(BaseModel):
    id: str
    number: int
    title: str
    shortDescription: Optional[str]
    createdAt: str
    updatedAt: str
    closed: bool
    url: str

    @property
    def state(self) -> ProjectState:
        return ProjectState.CLOSED if self.closed else ProjectState.OPEN


# ───────────────────────────── helper parse --────────────────────────────────
def _parse_project_nodes(resp: Dict[str, Any]) -> List[ProjectNode]:
    nodes = resp["user"]["projectsV2"]["nodes"]  # or ["organization"]
    return [ProjectNode.model_validate(n) for n in nodes]


# ─────────────────────────── manager class ────────────────────────────────────
class ProjectManager(BaseModel):
    """
    CRUD operations for Projects v2.
    Mirrors IssueManager / DiscussionManager ergonomics.
    """

    client: Any = Field(..., exclude=True)
    model_config = dict(arbitrary_types_allowed=True)

    # list --------------------------------------------------------------------
    def list_projects(
        self,
        owner: str,
        first: int = 50,
        state: Optional[ProjectState] = None,
    ) -> List[ProjectNode]:
        vars_: Dict[str, Any] = {"owner": owner, "first": first}
        projects: List[ProjectNode] = []
        for page in self.client.client.graphql.paginate(LIST_PROJECTS_QUERY, vars_):
            page_nodes = _parse_project_nodes(page)
            if state:
                page_nodes = [p for p in page_nodes if p.state == state]
            projects.extend(page_nodes)
        return projects

    # create ------------------------------------------------------------------
    def create_project(self, owner_id: str, title: str) -> ProjectNode:
        data = self.client.graphql(
            CREATE_PROJECT_MUTATION, {"ownerId": owner_id, "title": title}
        )
        return ProjectNode.model_validate(data["createProjectV2"]["projectV2"])

    # update ------------------------------------------------------------------
    def update_project(
        self,
        project_id: str,
        *,
        title: Optional[str] = None,
        short_description: Optional[str] = None,
        closed: Optional[bool] = None,
    ) -> ProjectNode:
        vars_: Dict[str, Any] = {
            "projectId": project_id,
            "title": title,
            "shortDescription": short_description,
            "closed": closed,
        }
        vars_ = {k: v for k, v in vars_.items() if v is not None}
        data = self.client.graphql(UPDATE_PROJECT_MUTATION, vars_)
        return ProjectNode.model_validate(data["updateProjectV2"]["projectV2"])

    # delete ------------------------------------------------------------------
    def delete_project(self, project_id: str) -> str:
        """
        Removes a project; returns the `deletedItemId` echoed by GitHub.
        """
        data = self.client.graphql(DELETE_PROJECT_MUTATION, {"projectId": project_id})
        return data["deleteProjectV2"]["deletedItemId"]
