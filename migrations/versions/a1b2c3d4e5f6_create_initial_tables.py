"""create initial tables

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-09-21 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'role',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nome'),
    )
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('password', sa.String(), nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['role.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
        sa.UniqueConstraint('email'),
    )
    op.create_table(
        'carteira',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nome', 'owner_id'),
    )
    op.create_table(
        'key_account',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nome', 'owner_id'),
    )
    op.create_table(
        'carteira_key_account',
        sa.Column('carteira_id', sa.Integer(), nullable=False),
        sa.Column('key_account_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['carteira_id'], ['carteira.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['key_account_id'], ['key_account.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('carteira_id', 'key_account_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('carteira_key_account')
    op.drop_table('key_account')
    op.drop_table('carteira')
    op.drop_table('users')
    op.drop_table('role')
