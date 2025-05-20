# ── std-lib ───────────────────────────────────────────────────────────────────
from typing import Any, Dict, List, Optional

# ── third-party ───────────────────────────────────────────────────────────────
from pydantic import BaseModel, Field

# ───────────────────────── GraphQL documents ─────────────────────────────────
# ---- LIST ----------------------------------------------------------
LIST_DISCUSSION_COMMENTS_QUERY = """
query ListDiscussionComments(
  $owner: String!
  $name:  String!
  $number: Int!
  $first: Int = 100
  $after: String
){
  repository(owner: $owner, name: $name) {
    discussion(number: $number) {
      id
      title
      comments(first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          body
          createdAt
          updatedAt
          author { login }
        }
      }
    }
  }
}
"""

# ---- CREATE --------------------------------------------------------
ADD_DISCUSSION_COMMENT_MUTATION = """
mutation AddDiscussionComment(
  $discussionId: ID!
  $body: String!                    # body is NON-NULL (String!)
){
  addDiscussionComment(
    input: { discussionId: $discussionId, body: $body }
  ) {
    comment {
      id
      body
      createdAt
      updatedAt
      author { login }
    }
  }
}
"""

# ---- UPDATE --------------------------------------------------------
UPDATE_DISCUSSION_COMMENT_MUTATION = """
mutation UpdateDiscussionComment(
  $commentId: ID!
  $body: String!                    # must be non-null
){
  updateDiscussionComment(
    input: { commentId: $commentId, body: $body }
  ) {
    comment {
      id
      body
      createdAt
      updatedAt
      author { login }
    }
  }
}
"""

# ---- DELETE --------------------------------------------------------
DELETE_DISCUSSION_COMMENT_MUTATION = """
mutation DeleteDiscussionComment($id: ID!){
  deleteDiscussionComment(input:{id:$id}) {
    comment { id body }
  }
}
"""


# ─────────────────────────── data models ──────────────────────────────────────
class _User(BaseModel):
    login: str


class DiscussionCommentNode(BaseModel):
    id: str
    body: str
    createdAt: str
    updatedAt: str
    author: _User
    # path: Optional[str]


# ────────────────────────── helper function ──────────────────────────────────
def _parse_comment_nodes(resp: Dict[str, Any]) -> List[DiscussionCommentNode]:
    nodes = resp["repository"]["discussion"]["comments"]["nodes"]
    return [DiscussionCommentNode.model_validate(n) for n in nodes]


# ──────────────────────── manager class ───────────────────────────────────────
class DiscussionCommentManager(BaseModel):
    """
    CRUD operations for comments inside a single discussion.
    Mirrors the style of IssueManager / DiscussionManager.
    """

    client: Any = Field(..., exclude=True)  # GitHubClient instance
    model_config = dict(arbitrary_types_allowed=True)

    # list comments -----------------------------------------------------------
    def list_comments(
        self,
        owner: str,
        repo: str,
        discussion_number: int,
        first: int = 100,
    ) -> List[DiscussionCommentNode]:
        vars_: Dict[str, Any] = {
            "owner": owner,
            "name": repo,
            "number": discussion_number,
            "first": first,
        }
        comments: List[DiscussionCommentNode] = []
        for page in self.client.client.graphql.paginate(
            LIST_DISCUSSION_COMMENTS_QUERY,
            variables=vars_,
        ):
            comments.extend(_parse_comment_nodes(page))
        return comments

    # create comment ----------------------------------------------------------
    def add_comment(self, discussion_id: str, body: str) -> DiscussionCommentNode:
        data = self.client.graphql(
            ADD_DISCUSSION_COMMENT_MUTATION,
            {"discussionId": discussion_id, "body": body},
        )
        return DiscussionCommentNode.model_validate(
            data["addDiscussionComment"]["comment"]
        )

    # update comment ----------------------------------------------------------
    def update_comment(self, comment_id: str, body: str) -> DiscussionCommentNode:
        data = self.client.graphql(
            UPDATE_DISCUSSION_COMMENT_MUTATION,
            {"commentId": comment_id, "body": body},
        )
        return DiscussionCommentNode.model_validate(
            data["updateDiscussionComment"]["comment"]
        )

    # delete comment ----------------------------------------------------------
    def delete_comment(self, comment_id: str) -> Dict[str, Any]:
        data = self.client.graphql(
            DELETE_DISCUSSION_COMMENT_MUTATION, {"id": comment_id}
        )
        return data["deleteDiscussionComment"]["comment"]
