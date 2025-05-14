from app import db

def upgrade():
    # Добавляем колонку session_token
    db.engine.execute('ALTER TABLE user ADD COLUMN session_token VARCHAR(100) UNIQUE')

def downgrade():
    # Удаляем колонку session_token
    db.engine.execute('ALTER TABLE user DROP COLUMN session_token') 