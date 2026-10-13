import argparse
import getpass

from sqlalchemy import select
from sqlalchemy.orm import Session

from researchos.core.config import Settings
from researchos.core.security import hash_password, normalize_email
from researchos.domain.models import User
from researchos.infrastructure.database import build_engine


def provision_user(db: Session, email: str, password: str) -> User:
    email = normalize_email(email)
    if db.scalar(select(User.id).where(User.email_normalized == email)) is not None:
        raise ValueError("Account already exists")
    user = User(email_normalized=email, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    return user


def main():
    parser = argparse.ArgumentParser(description="ResearchOS local account provisioning")
    parser.add_argument("command", choices=["create-user"])
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Password (12-256 characters): ")
    if password != getpass.getpass("Confirm password: "):
        parser.exit(1, "Passwords do not match\n")
    engine = build_engine(Settings())
    try:
        with Session(engine) as db, db.begin():
            provision_user(db, args.email, password)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    except Exception:
        parser.exit(1, "Account provisioning failed; check database availability\n")
    finally:
        engine.dispose()
    print("Account created")


if __name__ == "__main__":
    main()
