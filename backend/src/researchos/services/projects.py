import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from researchos.api.errors import ApiError
from researchos.domain.models import Paper, PaperProject, Project, User
from researchos.services.resources import require_revision


def owned_project(db: Session, owner: uuid.UUID, identifier: uuid.UUID, lock=False) -> Project:
    query = select(Project).where(Project.owner_id == owner, Project.id == identifier)
    if lock:
        query = query.with_for_update()
    project = db.scalar(query)
    if project is None:
        raise ApiError(404, "project_not_found", "Project not found")
    return project


def create_project(db: Session, owner: uuid.UUID, name: str, description: str) -> Project:
    project = Project(owner_id=owner, name=name, description=description)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def change_project(
    db: Session, owner: uuid.UUID, identifier: uuid.UUID, changes: dict, match: str | None
):
    project = owned_project(db, owner, identifier, lock=True)
    require_revision(project, match)
    for key, value in changes.items():
        if key == "archived":
            project.archived_at = datetime.now(UTC) if value else None
        else:
            setattr(project, key, value)
    project.revision += 1
    project.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, owner: uuid.UUID, identifier: uuid.UUID, match: str | None):
    db.scalar(select(User.id).where(User.id == owner).with_for_update())
    project = owned_project(db, owner, identifier, lock=True)
    require_revision(project, match)
    linked = select(PaperProject.paper_id).where(
        PaperProject.owner_id == owner, PaperProject.project_id == identifier
    )
    db.execute(
        update(Paper)
        .where(Paper.owner_id == owner, Paper.id.in_(linked))
        .values(revision=Paper.revision + 1, updated_at=datetime.now(UTC))
    )
    db.delete(project)
    db.commit()
