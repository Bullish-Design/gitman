# sync_issues.py
import os
from dotenv import load_dotenv
from pprint import pprint as pp
from sqlmodel import Field, SQLModel, Session, create_engine, select
from githubkit import GitHub
from datetime import datetime
from typing import List
from pydantic import BaseModel
from uuid import UUID, uuid4
from sqlalchemy.dialects.sqlite import insert


import uuid

from .config import GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO, DATABASE_URL


# Load environment variables from .env in project root
load_dotenv()  # reads key‑value pairs from .env into os.environ :contentReference[oaicite:0]{index=0}


# 1. Define SQLModel entity
class Issue(SQLModel, table=True):
    id: str = Field(primary_key=True)
    gh_number: int = Field(index=True)
    title: str
    body: str


class DiscussionNode(SQLModel, table=True):
    """
    Persists one Discussion entry.
    """

    id: str = Field(primary_key=True)
    number: int = Field(index=True)
    title: str
    body_text: str = Field(alias="bodyText")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        allow_population_by_field_name = True
        orm_mode = True


class Discussions(SQLModel):
    """
    Wraps the list of DiscussionNode objects.
    """

    nodes: List[DiscussionNode]


class Repository(SQLModel):
    """
    Top‑level repository container.
    """

    discussions: Discussions


class DiscussionsResponse(SQLModel):
    """
    Full GraphQL response.
    """

    repository: Repository


# 2. Setup DB & GitHub client using .env values
engine = create_engine(DATABASE_URL, echo=False)

OWNER = GITHUB_OWNER
REPO = GITHUB_REPO

SQLModel.metadata.create_all(engine)
client = GitHub(GITHUB_TOKEN)


def upsert(session: Session, instance: SQLModel) -> None:
    """
    Perform an upsert of the given SQLModel instance:
      - INSERT ... ON CONFLICT (pk) DO UPDATE SET ... for non-PK columns.
    """
    model = type(instance)
    data = instance.model_dump()

    # Build the SQLite dialect Insert
    stmt = insert(model).values(**data)

    # Identify primary key columns
    pk_cols = [col.name for col in model.__table__.primary_key]

    # Prepare the excluded‑based update mapping
    update_cols = {k: stmt.excluded[k] for k in data.keys() if k not in pk_cols}

    # Attach ON CONFLICT DO UPDATE
    stmt = stmt.on_conflict_do_update(index_elements=pk_cols, set_=update_cols)

    # Execute the upsert
    session.execute(stmt)


def pretty_print_model(model: BaseModel) -> None:
    """
    Pretty‑print a Pydantic model’s class name, and for each field:
    - field name
    - type annotation
    - current value
    """
    cls_name = model.__class__.__name__
    print(f"\n\n{cls_name}:")
    for name, field_info in model.model_fields.items():
        # Extract annotation and value
        annotation = field_info.annotation
        value = getattr(model, name)
        # Format type as a human‑readable string
        type_str = getattr(annotation, "__name__", repr(annotation))
        type_and_name_str = f"{name:15} [{type_str}]"
        print(f"  • {type_and_name_str:35} {value!r}")


def github_issues_to_db():  # ToDo: Add an input parameter for the GitHub repo
    with Session(engine) as session:
        gh_issues = client.rest.issues.list_for_repo(owner=OWNER, repo=REPO)
        print(f"\n\nGitHub Issues: \n{gh_issues}\n\n")
        parsed_issues = gh_issues.parsed_data
        print(f"\nParsed: \n{parsed_issues}\n\n")
        print(f"Found {len(parsed_issues)} issues in GitHub repo {OWNER}/{REPO}.\n")
        for gh in parsed_issues:
            # @print(f"\n{type(gh)} - {gh}\n\n{gh.number} {gh.title} {gh.body}\n\n")
            contents = gh.model_dump()
            print(f"\n{type(gh)}:")
            pp(contents)
            issue = Issue(
                id=gh.id, gh_number=gh.number, title=gh.title, body=gh.body or ""
            )
            # session.add(issue)
            upsert(session, issue)

        print(f"\n\n\nCommiting GitHub Issues to DB:\n")
        session.commit()


def github_discussion_to_db():
    with Session(engine) as session:
        query = """
        query($owner:String!, $name:String!, $first:Int!) {
            repository(owner:$owner, name:$name) {
                discussions(first:$first) {
                nodes {
                    number
                    title
                    bodyText
                    createdAt
                    updatedAt
                    }
                }
            }
        }
        """

        gh_discussions = client.graphql(
            query, variables={"owner": OWNER, "name": REPO, "first": 100}
        )
        print(f"\n\nGitHub Discussions: \n{gh_discussions}\n\n")
        # parsed_discussions = gh_discussions.parsed_data
        print(f"\nReturn Val: \n{pp(gh_discussions)}\n\n")
        # print(
        #    f"Found {len(parsed_discussions)} discussions in GitHub repo {OWNER}/{REPO}.\n"
        # )
        parsed_discussions = DiscussionsResponse.parse_obj(gh_discussions)
        repo_discussions = parsed_discussions.repository.discussions.nodes
        for gh in repo_discussions:
            print(
                f"\n{type(gh).__name__}: {gh}\n\n{gh.number} - {gh.title} \n{gh.body_text}\n\n"
            )
            # pretty_print_model(gh)
            discussion_node = DiscussionNode(
                number=gh.number,
                title=gh.title,
                body_text=gh.body_text,
                created_at=gh.created_at,
                updated_at=gh.updated_at,
            )
            # print(f"\n{type(discussion_node)} - {discussion_node}\n\n")
            # pretty_print_model(discussion_node)
            # print(f"\n{type(gh).__name__}: \n    {gh}\n\n")
            # @print(f"\n{type(gh)} - {gh}\n\n{gh.number} {gh.title} {gh.body}\n\n")
            # contents = gh.model_dump()
            # print(f"\n{type(gh)}:")
            # pp(contents)
            # issue = Issue(gh_number=gh.number, title=gh.title, body=gh.body or "")
            # session.add(discussion_node)
            upsert(session, discussion_node)

        session.commit()


def db_to_github():
    with Session(engine) as session:
        stmt = select(Issue).where(Issue.gh_number == 0)
        new_issues = session.exec(stmt).all()
        for issue in new_issues:
            created = client.rest.issues.create_for_repo(
                owner=OWNER,
                repo=REPO,
                title=issue.title,
                body=issue.body,
            )
            issue.gh_number = created.number
        session.commit()


def main():
    github_issues_to_db()
    print(f"\n\n\nGitHub Issues to DB:\n")
    github_discussion_to_db()
    # db_to_github()


if __name__ == "__main__":
    main()
