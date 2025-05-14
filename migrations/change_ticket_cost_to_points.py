"""change ticket_cost to points_cost

Revision ID: change_ticket_cost_to_points
Revises: add_last_activity
Create Date: 2024-03-19 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'change_ticket_cost_to_points'
down_revision = 'add_last_activity'
branch_labels = None
depends_on = None

def upgrade():
    # Переименовываем колонку ticket_cost в points_cost
    op.alter_column('prize', 'ticket_cost', new_column_name='points_cost')

def downgrade():
    # Возвращаем старое название колонки
    op.alter_column('prize', 'points_cost', new_column_name='ticket_cost') 