# ── std-lib ───────────────────────────────────────────────────────────────────
from enum import Enum
from typing import Any, Dict, List, Optional
from pprint import pprint as pp

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


# ── small helper query to fetch IDs ------------------------------------------
OWNER_IDS_QUERY = """
query OwnerIds($login: String!) {
  user(login: $login)      { id login }
  #organization(login: $login) { id login }
}
"""

# projects.py  (add near other mutation strings)
ADD_ISSUE_TO_PROJECT_MUTATION = """
mutation AddIssueToProject($projectId: ID!, $issueId: ID!) {
  addProjectV2ItemById(
    input: { projectId: $projectId, contentId: $issueId }
  ) {
    item {                 # ProjectV2Item
      id
    }
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


class ProjectItem(BaseModel):
    id: str


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

    # --- internal ------------------------------------------------------------
    def _owner_id(self, login: str) -> str:
        """
        Return the new-style node-ID for a user *or* organization.
        Raises ValueError if login not found.
        """
        data = self.client.graphql(OWNER_IDS_QUERY, {"login": login})
        print(f"\n\n")
        pp(data)
        print(f"\n\n")
        if data.get("user"):
            return data["user"]["id"]
        if data.get("organization"):
            return data["organization"]["id"]
        raise ValueError(f"Login {login!r} not found")

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

    # --- create --------------------------------------------------------------
    def create_project(self, owner_login: str, title: str) -> ProjectNode:
        owner_id = self._owner_id(owner_login)
        data = self.client.graphql(
            CREATE_PROJECT_MUTATION,
            {"ownerId": owner_id, "title": title},
        )
        if data.get("createProjectV2") is None:  # permissions or wrong scope
            raise PermissionError(
                f"Token lacks permission to create projects in {owner_login!r}"
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

    #  add issue to project ----------------------------------------------------
    def add_issue(
        self,
        project_id: str,
        issue_id: str,
    ) -> ProjectItem:
        """
        Link an existing issue to a Project v2 board.

        Args:
            project_id: Node-ID of the project (ProjectV2 id).
            issue_id:   Node-ID of the issue (Issue id).

        Returns:
            ProjectItem with the new item’s id.
        """
        data = self.client.graphql(
            ADD_ISSUE_TO_PROJECT_MUTATION,
            {"projectId": project_id, "issueId": issue_id},
        )
        return ProjectItem.model_validate(data["addProjectV2ItemById"]["item"])

    # delete ------------------------------------------------------------------
    def delete_project(self, project_id: str) -> str:
        """
        Removes a project; returns the `deletedItemId` echoed by GitHub.
        """
        data = self.client.graphql(DELETE_PROJECT_MUTATION, {"projectId": project_id})
        return data["deleteProjectV2"]["deletedItemId"]
