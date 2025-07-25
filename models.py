from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from passlib.context import CryptContext

# Создаем базовый класс для моделей
Base = declarative_base()

# Создаем движок базы данных с явным указанием кодировки
import os
database_url = os.environ.get('SQLALCHEMY_DATABASE_URI')
engine = create_engine(
    database_url,
    connect_args={'client_encoding': 'utf8'}
)
SessionLocal = sessionmaker(bind=engine)

# Создаем контекст для хеширования паролей
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    educational_institution_id = Column(Integer, nullable=True)  # Временно, связь добавим ниже

    def verify_password(self, password):
        return pwd_context.verify(password, self.hashed_password)

    @staticmethod
    def get_password_hash(password):
        return pwd_context.hash(password)

class News(Base):
    __tablename__ = "news"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    short_description = Column(Text, nullable=False)
    full_content = Column(Text, nullable=False)
    image = Column(String(500), nullable=True)  # Путь к изображению
    is_published = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

# Создаем таблицы в базе данных (только если запускаем models.py напрямую)
if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    print("Таблицы созданы из models.py")

# Функция для получения сессии базы данных
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Функция для создания администратора
def create_admin_user():
    db = SessionLocal()
    try:
        # Проверяем, существует ли уже администратор
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                username="admin",
                email="admin@school-tournaments.ru",
                hashed_password=User.get_password_hash("admin123"),
                is_admin=True
            )
            db.add(admin)
            db.commit()
            print("Администратор успешно создан")
    except Exception as e:
        print(f"Ошибка при создании администратора: {e}")
    finally:
        db.close()

# Добавляем связь после определения обеих моделей
# ... после определения класса EducationalInstitution ...
# User.educational_institution = relationship('EducationalInstitution', backref='users') 