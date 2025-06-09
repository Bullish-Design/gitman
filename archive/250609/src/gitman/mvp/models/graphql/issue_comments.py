# ── std-lib ───────────────────────────────────────────────────────────────────
from typing import Any, Dict, List

# ── third-party ───────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field

# ── GraphQL documents ─────────────────────────────────────────────────────────
LIST_COMMENTS_QUERY = """
query ListIssueComments(
  $owner: String!
  $name:  String!
  $number:Int!
  $first: Int  = 100
  $after: String
){
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      comments(first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          body
          url
          createdAt
          updatedAt
          author { login }
        }
      }
    }
  }
}
"""

ADD_COMMENT_MUTATION = """
mutation AddComment(
  $subjectId: ID!
  $body: String!      # must be non-null
){
  addComment(input:{subjectId:$subjectId, body:$body}) {
    commentEdge {
      node {
        id
        body
        url
        createdAt
        updatedAt
        author { login }
      }
    }
  }
}
"""

UPDATE_COMMENT_MUTATION = """
mutation UpdateIssueComment(
  $id: ID!
  $body: String!      # GitHub requires non-null here too
){
  updateIssueComment(input:{id:$id, body:$body}) {
    issueComment {
      id
      body
      url
      createdAt
      updatedAt
      author { login }
      editor { login }
      lastEditedAt
    }
  }
}
"""

DELETE_COMMENT_MUTATION = """
mutation DeleteIssueComment($id: ID!){
  deleteIssueComment(input:{id:$id}) {
    clientMutationId       # nothing else returned
  }
}
"""


# ── data models ───────────────────────────────────────────────────────────────
class _User(BaseModel):
    login: str


class IssueCommentNode(BaseModel):
    id: str
    body: str
    url: str
    createdAt: str
    updatedAt: str
    author: _User


# ── parse helper ──────────────────────────────────────────────────────────────
def _parse_comment_nodes(resp: Dict[str, Any]) -> List[IssueCommentNode]:
    nodes = resp["repository"]["issue"]["comments"]["nodes"]
    return [IssueCommentNode.model_validate(n) for n in nodes]


# ── CommentManager ────────────────────────────────────────────────────────────
class IssueCommentManager(BaseModel):
    """
    CRUD wrapper for issue comments – mirrors IssueManager surface.
    """

    client: Any = Field(..., exclude=True)  # GitHubClient
    model_config = dict(arbitrary_types_allowed=True)

    # list ---------------------------------------------------------------------
    def list_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        first: int = 100,
    ) -> List[IssueCommentNode]:
        vars_: Dict[str, Any] = {
            "owner": owner,
            "name": repo,
            "number": issue_number,
            "first": first,
        }
        out: List[IssueCommentNode] = []
        for page in self.client.client.graphql.paginate(LIST_COMMENTS_QUERY, vars_):
            out.extend(_parse_comment_nodes(page))
        return out

    # create -------------------------------------------------------------------
    def add_comment(self, subject_id: str, body: str) -> IssueCommentNode:
        data = self.client.graphql(
            ADD_COMMENT_MUTATION, {"subjectId": subject_id, "body": body}
        )
        return IssueCommentNode.model_validate(
            data["addComment"]["commentEdge"]["node"]
        )

    # update -------------------------------------------------------------------
    def update_comment(self, comment_id: str, body: str) -> IssueCommentNode:
        data = self.client.graphql(
            UPDATE_COMMENT_MUTATION, {"id": comment_id, "body": body}
        )
        return IssueCommentNode.model_validate(
            data["updateIssueComment"]["issueComment"]
        )

    # delete -------------------------------------------------------------------
    def delete_comment(self, comment_id: str) -> None:
        """
        Delete a comment – GitHub returns only clientMutationId; swallow output.
        """
        self.client.graphql(DELETE_COMMENT_MUTATION, {"id": comment_id})
