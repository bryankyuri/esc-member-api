"""certificates + learner profile (first/last name)

Revision ID: 0005_certs
Revises: 0004_learning
Create Date: 2026-09-23

Phase 3 of PLATFORM-V2-SPEC.md (SPEC-CRT-01 … SPEC-CRT-05).

A certificate needs a real name on it, so `users` gains `first_name` and
`last_name`. These are the **learner** profile — deliberately not the member
profile (WhatsApp, domicile, Instagram), which stays required only for the
member area. Someone who never joined the club can still earn a certificate.

`first_name` is backfilled from the existing Google display name so current
members are not asked again for something we already know.
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_certs"
down_revision = "0004_learning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("first_name", sa.String(), nullable=True))
        batch.add_column(sa.Column("last_name", sa.String(), nullable=True))

    # Split the Google display name once: everything before the first space is
    # the first name, the rest is the surname. People can correct it when they
    # claim a certificate — which is why the certificate asks rather than
    # assumes.
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE users SET
          first_name = CASE
            WHEN instr(full_name, ' ') > 0
              THEN substr(full_name, 1, instr(full_name, ' ') - 1)
            ELSE full_name END,
          last_name = CASE
            WHEN instr(full_name, ' ') > 0
              THEN substr(full_name, instr(full_name, ' ') + 1)
            ELSE '' END
        WHERE full_name IS NOT NULL AND full_name <> ''
    """))

    op.create_table(
        "certificates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_slug", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("first_name_snapshot", sa.String(), nullable=False),
        sa.Column("last_name_snapshot", sa.String(), nullable=False),
        sa.Column("email_snapshot", sa.String(), nullable=False),
        sa.Column(
            "issued_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "course_slug", name="uq_certificate_user_course"),
    )
    op.create_index("ix_certificates_code", "certificates", ["code"], unique=True)
    op.create_index("ix_certificates_user_id", "certificates", ["user_id"])
    op.create_index("ix_certificates_course_slug", "certificates", ["course_slug"])


def downgrade() -> None:
    op.drop_table("certificates")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_name")
        batch.drop_column("first_name")
