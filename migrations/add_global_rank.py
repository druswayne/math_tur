from app import db

def upgrade():
    # Добавляем колонку global_rank
    db.engine.execute('ALTER TABLE user ADD COLUMN global_rank INTEGER')
 
def downgrade():
    # Удаляем колонку global_rank
    db.engine.execute('ALTER TABLE user DROP COLUMN global_rank') 