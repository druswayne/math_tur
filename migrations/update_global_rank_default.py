import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db

def upgrade():
    # Обновляем все NULL значения на 0
    db.engine.execute('UPDATE user SET global_rank = 0 WHERE global_rank IS NULL')

def downgrade():
    # Откат не требуется, так как мы просто устанавливаем значение по умолчанию
    pass 