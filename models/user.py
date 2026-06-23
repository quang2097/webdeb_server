from database import Base
from sqlalchemy import Column, String, Boolean, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

class User(Base):
    __tablename__ = "users"
    user_id = Column(UUID(as_uuid=True),primary_key=True, default=uuid.uuid4)
    user_name = Column(String,unique=True, nullable=False)
    user_hashedpassword = Column(String, nullable=False)
    user_email = Column(String, unique=True, nullable=False)
    
    user_role = Column(String, nullable=False, default="user")
    user_avatarurl = Column(String, nullable=False, default="https://images.vexels.com/media/users/3/143350/isolated/preview/150164edc7f28a716bfceae9dd58cf2c-coolface-trollface-meme-by-vexels.png")
    
    
    user_islocked = Column(Boolean, nullable=False, default=False)
    user_isactivated = Column(Boolean, nullable=False, default=False)

    otp = Column(String, nullable=True)

    novels = relationship("Novel", back_populates="uploader")
    reports = relationship("Report", back_populates="user", cascade="all, delete-orphan")
    
    __table_args__ = (
        CheckConstraint("user_role IN ('admin', 'user')", name="check_user_role"),
    )