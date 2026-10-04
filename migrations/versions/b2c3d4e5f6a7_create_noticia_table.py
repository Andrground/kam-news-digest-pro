"""create noticia table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-22 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'noticia',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key_account_id', sa.Integer(), nullable=False),
        sa.Column('url_hash', sa.String(length=64), nullable=False),
        sa.Column('texto', sa.String(), nullable=False),
        sa.Column('categoria', sa.String(), nullable=False),
        sa.Column('fonte', sa.String(), nullable=True),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('data_publicacao', sa.Date(), nullable=True),
        sa.Column('avaliacao', sa.String(), nullable=True),
        sa.Column('avaliado_por_id', sa.Integer(), nullable=True),
        sa.Column('avaliado_em', sa.DateTime(), nullable=True),
        sa.Column(
            'criada_em',
            sa.DateTime(),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'vista_em',
            sa.DateTime(),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['key_account_id'], ['key_account.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(['avaliado_por_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_account_id', 'url_hash'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('noticia')
