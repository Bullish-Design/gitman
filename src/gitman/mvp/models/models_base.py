from pydantic import BaseModel, HttpUrl, Field
from datetime import datetime
from typing import Optional


class UserSchema(BaseModel):
    """Subset of the GitHub SimpleUser payload we care about."""

    github_id: int = Field(..., alias="id")
    node_id: str
    login: str
    name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: HttpUrl
    html_url: HttpUrl
    type: str
    site_admin: bool = False

    model_config = {"from_attributes": True, "validate_by_name": True}

    # convenience accessor
    @property
    def owner_login(self) -> str:
        """Expose ``owner.login`` directly for quick look‑ups."""
        return self.owner.login


class IssueSchema(BaseModel):
    github_id: int
    repo: str
    title: str
    body: str

    model_config = {"from_attributes": True}


class CommentSchema(BaseModel):
    github_id: int = Field(..., alias="id")
    issue_id: int = Field(..., alias="issue_id")
    repo: str
    author_login: str
    body: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "validate_by_name": True}


class RepositorySchema(BaseModel):
    """Pydantic mirror of the *important* repo fields we store locally."""

    github_id: int = Field(..., alias="id")
    node_id: str
    name: str
    full_name: str
    owner: UserSchema  # = Field(..., alias="owner")
    private: bool
    description: Optional[str] = None
    html_url: HttpUrl
    default_branch: Optional[str] = None
    visibility: Optional[str] = None
    language: Optional[str] = None
    stargazers_count: Optional[int] = None
    forks_count: Optional[int] = None
    open_issues_count: Optional[int] = None
    pushed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    archived: Optional[bool] = None
    disabled: Optional[bool] = None

    model_config = {"from_attributes": True, "validate_by_name": True}
