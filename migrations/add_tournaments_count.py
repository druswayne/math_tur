from app import db

def upgrade():
    # Добавляем колонку tournaments_count
    db.engine.execute('ALTER TABLE user ADD COLUMN tournaments_count INTEGER DEFAULT 0')
    
    # Обновляем существующие записи
    db.engine.execute('''
        UPDATE user 
        SET tournaments_count = (
            SELECT COUNT(*) 
            FROM tournament_participation 
            WHERE tournament_participation.user_id = user.id
        )
    ''')

def downgrade():
    # Удаляем колонку tournaments_count
    db.engine.execute('ALTER TABLE user DROP COLUMN tournaments_count') 