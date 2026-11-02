from sqlalchemy import String, Integer, Text, LargeBinary, ForeignKey, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16), default='user')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    camera_mode: Mapped[str] = mapped_column(String(16), default='uvc')
    theme: Mapped[str] = mapped_column(String(16), default='dark')
    created_at: Mapped[str] = mapped_column(String(40))


class Upload(Base):
    __tablename__ = 'uploads'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    source: Mapped[str] = mapped_column(String(16))
    timestamp: Mapped[str] = mapped_column(String(40))
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    mime: Mapped[str] = mapped_column(String(40))


class Prediction(Base):
    __tablename__ = 'predictions'
    id: Mapped[str] = mapped_column(ForeignKey('uploads.id'), primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    block_index: Mapped[int] = mapped_column(Integer, unique=True)


class Block(Base):
    __tablename__ = 'blockchain_blocks'
    index: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[str] = mapped_column(String(40))
    data_hash: Mapped[str] = mapped_column(String(64))
    previous_hash: Mapped[str] = mapped_column(String(64))
    nonce: Mapped[int] = mapped_column(Integer)
    hash: Mapped[str] = mapped_column(String(64))


class ChainLock(Base):
    __tablename__ = 'chain_lock'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class Audit(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    timestamp: Mapped[str] = mapped_column(String(40))
    ip: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text, default='')


class Session(Base):
    __tablename__ = 'auth_sessions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    refresh_hash: Mapped[str] = mapped_column(String(64))
    expires: Mapped[int] = mapped_column(Integer)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class CameraTicket(Base):
    __tablename__ = 'camera_tickets'
    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    session_id: Mapped[str] = mapped_column(ForeignKey('auth_sessions.id'))
    expires: Mapped[int] = mapped_column(Integer)
