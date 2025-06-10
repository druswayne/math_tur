from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from passlib.context import CryptContext

# Создаем базовый класс для моделей
Base = declarative_base()

# Создаем движок базы данных с явным указанием кодировки
engine = create_engine(
    'postgresql://gen_user:qNCkZjwz12@89.223.64.134:5432/school_tournaments',
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

    def verify_password(self, password):
        return pwd_context.verify(password, self.hashed_password)

    @staticmethod
    def get_password_hash(password):
        return pwd_context.hash(password)

# Создаем таблицы в базе данных
Base.metadata.create_all(bind=engine)

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