import argparse
import getpass

from sqlalchemy import select
from sqlalchemy.orm import Session

from researchos.core.config import Settings
from researchos.core.security import hash_password, normalize_email
from researchos.domain.models import User
from researchos.infrastructure.database import build_engine
from researchos.infrastructure.storage import LocalFileStore
from researchos.services.maintenance import reconcile_storage


def provision_user(db: Session, email: str, password: str, *, is_admin: bool = False) -> User:
    email = normalize_email(email)
    if db.scalar(select(User.id).where(User.email_normalized == email)) is not None:
        raise ValueError("Account already exists")
    user = User(email_normalized=email, password_hash=hash_password(password), is_admin=is_admin)
    db.add(user)
    db.flush()
    return user


def grant_admin(db: Session, email: str):
    user = db.scalar(
        select(User).where(User.email_normalized == normalize_email(email)).with_for_update()
    )
    if user is None or not user.is_active:
        raise ValueError("An active account is required")
    if not user.is_admin:
        user.is_admin = True
        user.revision += 1


def main():
    parser = argparse.ArgumentParser(description="ResearchOS local account provisioning")
    parser.add_argument(
        "command", choices=["create-user", "create-admin", "grant-admin", "cleanup-storage"]
    )
    parser.add_argument("--email")
    args = parser.parse_args()
    engine = build_engine(Settings())
    if args.command == "cleanup-storage":
        try:
            with Session(engine) as db:
                result = reconcile_storage(db, LocalFileStore(Settings().storage_root))
            print(f"Cleaned pending={result['cleaned']} abandoned={result['orphaned']}")
        except Exception:
            parser.exit(1, "Storage maintenance failed\n")
        finally:
            engine.dispose()
        return
    if not args.email:
        parser.error("--email is required")
    password = None
    if args.command != "grant-admin":
        password = getpass.getpass("Password (12-256 characters): ")
        if password != getpass.getpass("Confirm password: "):
            parser.exit(1, "Passwords do not match\n")
    try:
        with Session(engine) as db, db.begin():
            if args.command == "grant-admin":
                grant_admin(db, args.email)
            else:
                provision_user(db, args.email, password, is_admin=args.command == "create-admin")
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    except Exception:
        parser.exit(1, "Account provisioning failed; check database availability\n")
    finally:
        engine.dispose()
    print("Administrator access granted" if args.command == "grant-admin" else "Account created")


if __name__ == "__main__":
    main()
