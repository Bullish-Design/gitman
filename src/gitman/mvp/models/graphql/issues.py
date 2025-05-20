# ── std-lib ────────────────────────────────────────────────────────────────────
from enum import Enum
from typing import Any, Dict, List, Optional

# ── third-party ───────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field

# ── GraphQL documents ─────────────────────────────────────────────────────────
LIST_ISSUES_QUERY = """
query ListIssues(
  $owner: String!
  $name:  String!
  $first: Int  = 100
  $after: String
){
  repository(owner: $owner, name: $name) {
    issues(first: $first, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        number
        title
        body
        url
        state   # IssueState enum
        createdAt
        updatedAt
        author { login }
      }
    }
  }
}
"""  # pagination pattern per GitHub docs :contentReference[oaicite:1]{index=1}

CREATE_ISSUE_MUTATION = """
mutation CreateIssue(
  $repositoryId: ID!
  $title: String!
  $body:  String
){
  createIssue(
    input: { repositoryId: $repositoryId, title: $title, body: $body }
  ) {
    issue {
      id
      number
      title
      body
      url
      state
      createdAt
      updatedAt
      author { login }
    }
  }
}
"""  # schema field `createIssue` :contentReference[oaicite:2]{index=2}

UPDATE_ISSUE_MUTATION = """
mutation UpdateIssue(
  $issueId: ID!
  $title: String
  $body:  String
  $state: IssueState
){
  updateIssue(
    input: { id: $issueId, title: $title, body: $body, state: $state }
  ) {
    issue {
      id
      number
      title
      body
      url
      state
      createdAt
      updatedAt
      author { login }
    }
  }
}
"""  # supports title/body edits and OPEN ↔ CLOSED state changes :contentReference[oaicite:3]{index=3}


# ── data models ───────────────────────────────────────────────────────────────
class _User(BaseModel):
    login: str


class IssueState(str, Enum):
    OPEN = "OPEN"
    CLOSED = (
        "CLOSED"  # enum values from IssueState :contentReference[oaicite:4]{index=4}
    )


class IssueNode(BaseModel):
    id: str
    number: int
    title: str
    body: Optional[str]
    url: str
    state: IssueState
    createdAt: str
    updatedAt: str
    author: _User


# ── helper to parse raw list response ─────────────────────────────────────────
def parse_issue_nodes(resp: Dict[str, Any]) -> List[IssueNode]:
    nodes = resp["repository"]["issues"]["nodes"]
    return [IssueNode.model_validate(n) for n in nodes]


# ── IssueManager (parallel to RepoManager) ────────────────────────────────────
class IssueManager(BaseModel):
    """
    All issue-level interactions for the authenticated user.
    Mirrors RepoManager’s public surface.
    """

    client: Any = Field(..., exclude=True)  # GitHubClient instance
    model_config = dict(arbitrary_types_allowed=True)

    # 1 – list issues ----------------------------------------------------------
    def list_issues(
        self,
        owner: str,
        repo: str,
        state: Optional[IssueState] = None,
        first: int = 100,
    ) -> List[IssueNode]:
        """
        Return every issue in `owner/repo` (optionally filtered by state).
        """
        variables: Dict[str, Any] = {"owner": owner, "name": repo, "first": first}
        nodes: List[IssueNode] = []

        for page in self.client.client.graphql.paginate(  # GitHubKit helper :contentReference[oaicite:5]{index=5}
            LIST_ISSUES_QUERY,
            variables=variables,
        ):
            page_nodes = parse_issue_nodes(page)
            if state:
                page_nodes = [n for n in page_nodes if n.state == state]
            nodes.extend(page_nodes)

        return nodes

    # 2 – create issue ---------------------------------------------------------
    def create_issue(
        self,
        repository_id: str,
        title: str,
        body: Optional[str] = None,
    ) -> IssueNode:
        vars_ = {"repositoryId": repository_id, "title": title, "body": body}
        data = self.client.graphql(CREATE_ISSUE_MUTATION, vars_)
        return IssueNode.model_validate(data["createIssue"]["issue"])

    # 3 – update / close issue -------------------------------------------------
    def update_issue(
        self,
        issue_id: str,
        *,
        title: Optional[str] = None,
        body: Optional[str] = None,
        state: Optional[IssueState] = None,
    ) -> IssueNode:
        vars_ = {
            "issueId": issue_id,
            "title": title,
            "body": body,
            "state": state.value if state else None,
        }
        # Remove None values so they’re not sent
        vars_ = {k: v for k, v in vars_.items() if v is not None}
        data = self.client.graphql(UPDATE_ISSUE_MUTATION, vars_)
        return IssueNode.model_validate(data["updateIssue"]["issue"])

    # Convenience: close without edits
    def close_issue(self, issue_id: str) -> IssueNode:
        """
        Shortcut to mark an issue CLOSED (GraphQL has no hard-delete).
        """
        return self.update_issue(issue_id, state=IssueState.CLOSED)
