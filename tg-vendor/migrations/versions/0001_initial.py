"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "users",
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("sender_address", sa.Text(), nullable=True),
        sa.Column("sender_address_verified", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("balance_usdt", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("total_spent", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("tg_id"),
        sa.UniqueConstraint("sender_address", name="uq_sender"),
    )

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("price_paid", sa.Numeric(12, 4), nullable=False),
        sa.Column("lzt_price_usd", sa.Numeric(12, 4), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("login_code", sa.Text(), nullable=True),
        sa.Column("twofa_password", sa.Text(), nullable=True),
        sa.Column("session_path", sa.Text(), nullable=True),
        sa.Column("fail_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.tg_id"], name="fk_orders_user"),
        sa.CheckConstraint(
            "status IN ('PENDING','PURCHASING','DELIVERED','FAILED','REFUNDED')",
            name="chk_order_status",
        ),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_status", "orders", ["status"])

    op.create_table(
        "deposits",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("tx_hash", sa.Text(), nullable=False),
        sa.Column("from_address", sa.Text(), nullable=False),
        sa.Column("to_address", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("block_ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("credited_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tx_hash", name="uq_deposits_tx_hash"),
        sa.ForeignKeyConstraint(["user_id"], ["users.tg_id"], name="fk_deposits_user"),
    )
    op.create_index("ix_deposits_user_id", "deposits", ["user_id"])

    op.create_table(
        "tron_cursor",
        sa.Column("id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_block_ts", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO tron_cursor (id, last_block_ts) VALUES (1, 0)")

    op.create_table(
        "inventory_cache",
        sa.Column("item_id", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("price_usd", sa.Numeric(12, 4), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("premium", sa.Boolean(), nullable=True),
        sa.Column("spam_block", sa.Boolean(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(), nullable=True),
        sa.Column("last_seen", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("item_id"),
    )

    op.create_table(
        "unmatched_deposits",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tx_hash", sa.Text(), nullable=False),
        sa.Column("from_address", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("block_ts", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tx_hash", name="uq_unmatched_tx_hash"),
    )


def downgrade() -> None:
    op.drop_table("unmatched_deposits")
    op.drop_table("inventory_cache")
    op.drop_table("tron_cursor")
    op.drop_index("ix_deposits_user_id", "deposits")
    op.drop_table("deposits")
    op.drop_index("ix_orders_status", "orders")
    op.drop_index("ix_orders_user_id", "orders")
    op.drop_table("orders")
    op.drop_table("users")
