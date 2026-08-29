import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.models.user import User, UserRole
from sqlalchemy import select

async def main():
    async with SessionLocal() as s:
        rows = (await s.scalars(select(User).where(User.phone == "19943211891"))).all()
        if not rows:
            print("NOT FOUND: 该手机号未注册")
            return
        for u in rows:
            roles = (await s.scalars(select(UserRole).where(UserRole.user_id == u.id))).all()
            print(f"id: {u.id}")
            print(f"phone: {u.phone}")
            print(f"nickname: {getattr(u, 'nickname', None)}")
            print(f"status: {getattr(u, 'status', None)}")
            print(f"password_hash set: {bool(u.password_hash)}")
            print(f"password_hash: {u.password_hash!r}"[:200])
            print(f"roles: {[(r.role, r.scope_key) for r in roles]}")

asyncio.run(main())