from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///local.db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

Base = declarative_base()


class Issue(Base):
    __tablename__ = "issues"

    id = Column(Integer, primary_key=True, index=True)
    github_id = Column(Integer, unique=True, index=True)
    repo = Column(String)
    title = Column(String)
    body = Column(Text)


class Comment(Base):
    """Issue comments are stored in their own table – best‑practice normalisation."""

    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    github_id = Column(Integer, unique=True, index=True)  # comment.id from GitHub
    issue_id = Column(Integer, index=True)  # GitHub issue id (not FK enforced)
    repo = Column(String, index=True)
    author_login = Column(String)
    body = Column(Text)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class User(Base):
    """Basic GitHub user (SimpleUser) subset."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)  # local row id
    github_id = Column(Integer, unique=True, index=True)  # user.id from GitHub
    node_id = Column(String, unique=True)
    login = Column(String, index=True, nullable=False)
    name = Column(String)
    email = Column(String)
    avatar_url = Column(String)
    html_url = Column(String)
    type = Column(String)
    site_admin = Column(Boolean, default=False)


class Repository(Base):
    """Subset of GitHub repository fields we care about for syncing."""

    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, index=True)  # local row id
    github_id = Column(Integer, unique=True, index=True)  # repo.id from GitHub
    node_id = Column(String, unique=True)
    name = Column(String, index=True)
    full_name = Column(String)
    owner_login = Column(String, index=True)
    private = Column(Boolean, default=False)
    description = Column(Text)
    html_url = Column(String)
    default_branch = Column(String)
    visibility = Column(String)
    language = Column(String)
    stargazers_count = Column(Integer)
    forks_count = Column(Integer)
    open_issues_count = Column(Integer)
    pushed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime)
    archived = Column(Boolean)
    disabled = Column(Boolean)


Base.metadata.create_all(bind=engine)
