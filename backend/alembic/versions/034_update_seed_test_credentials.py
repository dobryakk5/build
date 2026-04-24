"""
034_update_seed_test_credentials.py
Обновляет учётные данные тестового сид-аккаунта.
"""

from alembic import op
from sqlalchemy.sql import text

from app.core.security import hash_password


revision = "034_update_seed_test_credentials"
down_revision = "033_estimate_batch_hours_per_day"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        text(
            """
            UPDATE users
            SET email = :new_email,
                password_hash = :password_hash
            WHERE id = CAST(:user_id AS uuid)
               OR lower(email) IN ('test@example.com', 'test@test.local', 'test@mail.ru')
            """
        ).bindparams(
            user_id="b0000000-0000-0000-0000-000000000001",
            new_email="test@mail.ru",
            password_hash=hash_password("test"),
        )
    )


def downgrade():
    op.execute(
        text(
            """
            UPDATE users
            SET email = :old_email,
                password_hash = :password_hash
            WHERE id = CAST(:user_id AS uuid)
               OR lower(email) = :new_email
            """
        ).bindparams(
            user_id="b0000000-0000-0000-0000-000000000001",
            old_email="test@example.com",
            new_email="test@mail.ru",
            password_hash=hash_password("test123"),
        )
    )
