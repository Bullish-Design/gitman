# Imports


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


# Mutation Strings


# Pydantic Models


# Misc
