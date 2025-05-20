# Query Strings
query = """
        query GetDiscussions($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            discussions(first: 50) {
              nodes {
                id
                title
                body
                url
                createdAt
                author {
                  login
                  url
                }
                category {
                  id
                  name
                  emoji
                }
                comments(first: 10) {
                  nodes {
                    body
                    createdAt
                    author {
                      login
                      url
                    }
                  }
                }
              }
            }
          }
        }
        """


# Imports  ──────────────────────────────────────────────────────────────
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# ── GraphQL documents ─────────────────────────────────────────────────────────
LIST_DISCUSSIONS_QUERY = """
query ListDiscussions(
  $owner: String!
  $name:  String!
  $first: Int = 100
  $after: String
){
  repository(owner: $owner, name: $name) {
    discussions(first: $first, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        number
        title
        body
        url
        createdAt          # ← now included
        updatedAt
        author { login }
        category { id name }
      }
    }
  }
}
"""

CREATE_DISCUSSION_MUTATION = """
mutation CreateDiscussion(
  $repositoryId: ID!
  $categoryId: ID!
  $title: String!
  $body:  String!
){
  createDiscussion(
    input: {
      repositoryId: $repositoryId
      categoryId:  $categoryId
      title:       $title
      body:        $body
    }
  ) {
    discussion {
      id
      number
      title
      body
      url
      createdAt      # ← now included
      updatedAt
      author { login }
      category { id name }
    }
  }
}
"""

UPDATE_DISCUSSION_MUTATION = """
mutation UpdateDiscussion(
  $discussionId: ID!
  $title: String
  $body:  String
  $categoryId: ID
){
  updateDiscussion(
    input: {
      discussionId: $discussionId
      title:        $title
      body:         $body
      categoryId:   $categoryId
    }
  ) {
    discussion {
      id
      number
      title
      body
      url
      createdAt      # ← now included
      updatedAt
      author { login }
      category { id name }
    }
  }
}
"""

DELETE_DISCUSSION_MUTATION = """
mutation DeleteDiscussion($id: ID!){
  deleteDiscussion(input:{id:$id}) {
    discussion { id number title createdAt updatedAt }
  }
}
"""

# ── GraphQL document ──────────────────────────────────────────────────────────
LIST_DISCUSSION_CATEGORIES_QUERY = """
query ListDiscussionCategories(
  $owner: String!
  $name:  String!
  $first: Int  = 100
  $after: String
){
  repository(owner: $owner, name: $name) {
    discussionCategories(first: $first, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        name
        description
        emoji     # e.g. "💬"
        isAnswerable
        #isDeprecated
        createdAt
        updatedAt
      }
    }
  }
}
"""


# ── Pydantic model ────────────────────────────────────────────────────────────
class DiscussionCategoryNode(BaseModel):
    id: str
    name: str
    description: Optional[str]
    emoji: Optional[str]
    isAnswerable: bool
    # isDeprecated: bool
    createdAt: str
    updatedAt: str


# ── data models ───────────────────────────────────────────────────────────────
class _User(BaseModel):
    login: str


class _Category(BaseModel):
    id: str
    name: str


class DiscussionNode(BaseModel):
    id: str
    number: int
    title: str
    body: Optional[str]
    url: str
    createdAt: str  # ← new
    updatedAt: str
    author: _User
    category: _Category


# ── parsing helper ────────────────────────────────────────────────────────────
def _parse_discussion_nodes(resp: Dict[str, Any]) -> List[DiscussionNode]:
    nodes = resp["repository"]["discussions"]["nodes"]
    return [DiscussionNode.model_validate(n) for n in nodes]


# ── manager class ─────────────────────────────────────────────────────────────
class DiscussionManager(BaseModel):
    client: Any = Field(..., exclude=True)
    model_config = dict(arbitrary_types_allowed=True)

    def list_discussions(
        self, owner: str, repo: str, first: int = 100
    ) -> List[DiscussionNode]:
        vars_ = {"owner": owner, "name": repo, "first": first}
        results: List[DiscussionNode] = []
        for page in self.client.client.graphql.paginate(LIST_DISCUSSIONS_QUERY, vars_):
            results.extend(_parse_discussion_nodes(page))
        return results

    def create_discussion(
        self,
        repository_id: str,
        category_id: str,
        title: str,
        body: Optional[str] = None,
    ) -> DiscussionNode:
        vars_ = {
            "repositoryId": repository_id,
            "categoryId": category_id,
            "title": title,
            "body": body,
        }
        data = self.client.graphql(CREATE_DISCUSSION_MUTATION, vars_)
        return DiscussionNode.model_validate(data["createDiscussion"]["discussion"])

    def update_discussion(
        self,
        discussion_id: str,
        *,
        title: Optional[str] = None,
        body: Optional[str] = None,
        category_id: Optional[str] = None,
    ) -> DiscussionNode:
        vars_ = {
            "discussionId": discussion_id,
            "title": title,
            "body": body,
            "categoryId": category_id,
        }
        vars_ = {k: v for k, v in vars_.items() if v is not None}
        data = self.client.graphql(UPDATE_DISCUSSION_MUTATION, vars_)
        return DiscussionNode.model_validate(data["updateDiscussion"]["discussion"])

    def delete_discussion(self, discussion_id: str) -> Dict[str, Any]:
        data = self.client.graphql(DELETE_DISCUSSION_MUTATION, {"id": discussion_id})
        return data["deleteDiscussion"]["discussion"]

        # list categories ----------------------------------------------------------

    def list_categories(
        self,
        owner: str,
        repo: str,
        first: int = 100,
    ) -> List[DiscussionCategoryNode]:
        """
        Return every discussion category (including name, emoji, etc.)
        for `owner/repo`.
        """
        variables: Dict[str, Any] = {"owner": owner, "name": repo, "first": first}
        nodes: List[DiscussionCategoryNode] = []

        for page in self.client.client.graphql.paginate(
            LIST_DISCUSSION_CATEGORIES_QUERY,
            variables=variables,
        ):
            page_nodes = page["repository"]["discussionCategories"]["nodes"]
            nodes.extend(DiscussionCategoryNode.model_validate(n) for n in page_nodes)

        return nodes
