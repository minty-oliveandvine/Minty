"""add connected_by_user_id and user_token

Revision ID: 37799fa97f37
Revises: f731e24bfe62
Create Date: 2026-05-14 15:56:27.348599

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '37799fa97f37'
down_revision = 'f731e24bfe62'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('entities', schema='pettycashv2') as batch_op:
        batch_op.add_column(sa.Column('connected_by_user_id', sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            'fk_entities_connected_by_user_id',
            'user',
            ['connected_by_user_id'], ['id'],
            referent_schema='pettycashv2',
            ondelete='RESTRICT',
        )

    op.create_table(
        'user_token',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('access_token', sa.Text(), nullable=True),
        sa.Column('access_token_obtained_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('access_token_expires_in', sa.Integer(), nullable=True),
        sa.Column('refresh_token', sa.Text(), nullable=True),
        sa.Column('id_token', sa.Text(), nullable=True),
        sa.Column('refresh_token_last_used_at', sa.TIMESTAMP(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['pettycashv2.user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
        schema='pettycashv2',
    )


def downgrade():
    op.drop_table('user_token', schema='pettycashv2')

    with op.batch_alter_table('entities', schema='pettycashv2') as batch_op:
        batch_op.drop_constraint('fk_entities_connected_by_user_id', type_='foreignkey')
        batch_op.drop_column('connected_by_user_id')
