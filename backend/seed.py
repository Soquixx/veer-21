from __future__ import annotations

import argparse
from uuid import uuid4

from .db.models import User
from .db.session import SessionLocal, create_tables
from .security import hash_password


def main() -> None:
    ap = argparse.ArgumentParser(description="Create or update a local development user.")
    ap.add_argument("--username", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--role", choices=["viewer", "planner", "approver"], default="planner")
    args = ap.parse_args()
    create_tables()
    with SessionLocal.begin() as db:
        user = db.query(User).filter(User.username == args.username).first()
        if not user:
            user = User(id=uuid4().hex, username=args.username, password_hash=hash_password(args.password), role=args.role)
            db.add(user)
        else:
            user.password_hash = hash_password(args.password)
            user.role = args.role
        print(f"user ready: {user.username} ({user.role})")


if __name__ == "__main__":
    main()
