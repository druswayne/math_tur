from app import db

def upgrade():
    # Добавляем колонку last_activity
    db.engine.execute('ALTER TABLE user ADD COLUMN last_activity DATETIME')

def downgrade():
    # Удаляем колонку last_activity
    db.engine.execute('ALTER TABLE user DROP COLUMN last_activity') 