import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, String, Unicode, UnicodeText, Integer, Float, Boolean, ForeignKey, Index, text, inspect, BigInteger, LargeBinary
from sqlalchemy.dialects.mssql import VARBINARY
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now():
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(Unicode(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    auth_version: Mapped[int] = mapped_column(Integer, default=1)
    phone: Mapped[str] = mapped_column(String(30), default='')
    vehicle: Mapped[str] = mapped_column(Unicode(100), default='')
    created: Mapped[str] = mapped_column(String(40), default=now)


class Order(Base):
    __tablename__ = 'delivery_orders'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(Unicode(150))
    phone: Mapped[str] = mapped_column(String(30), default='')
    address: Mapped[str] = mapped_column(Unicode(300))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    note: Mapped[str] = mapped_column(Unicode(500), default='')
    service_minutes: Mapped[float] = mapped_column(Float, default=3)
    cod: Mapped[int] = mapped_column(Integer, default=0)
    cod_collected: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default='pending')
    shipper_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True, index=True)
    failure_reason: Mapped[str] = mapped_column(Unicode(500), default='')
    version: Mapped[int] = mapped_column(Integer, default=1)
    created: Mapped[str] = mapped_column(String(40), default=now)
    updated: Mapped[str] = mapped_column(String(40), default=now)


class Setting(Base):
    __tablename__ = 'settings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[str] = mapped_column(UnicodeText)


class Parcel(Base):
    __tablename__ = 'order_parcels'
    order_id: Mapped[str] = mapped_column(ForeignKey('delivery_orders.id'), primary_key=True)
    item_name: Mapped[str] = mapped_column(Unicode(150))
    quantity: Mapped[int] = mapped_column(Integer)
    weight_kg: Mapped[float] = mapped_column(Float)
    goods_type: Mapped[str] = mapped_column(String(30))
    declared_value: Mapped[int] = mapped_column(Integer)
    shipping_fee: Mapped[int] = mapped_column(Integer)
    fee_payer: Mapped[str] = mapped_column(String(20))
    fee_collected: Mapped[bool] = mapped_column(Boolean, default=False)
    fee_basis: Mapped[str] = mapped_column(UnicodeText)


class Proof(Base):
    __tablename__ = 'delivery_proofs'
    order_id: Mapped[str] = mapped_column(ForeignKey('delivery_orders.id'), primary_key=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    receiver_name: Mapped[str] = mapped_column(Unicode(150))
    note: Mapped[str] = mapped_column(Unicode(500))
    image: Mapped[bytes] = mapped_column(LargeBinary().with_variant(VARBINARY(None), 'mssql'))
    created: Mapped[str] = mapped_column(String(40), default=now)


class Remittance(Base):
    __tablename__ = 'cod_remittances'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    staff_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    total: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    note: Mapped[str] = mapped_column(Unicode(500), default='')
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    review_note: Mapped[str] = mapped_column(Unicode(500), default='')
    created: Mapped[str] = mapped_column(String(40), default=now)
    reviewed: Mapped[str | None] = mapped_column(String(40), nullable=True)


class RemittanceItem(Base):
    __tablename__ = 'cod_remittance_items'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    remittance_id: Mapped[str] = mapped_column(ForeignKey('cod_remittances.id'), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('delivery_orders.id'), index=True)
    cod_amount: Mapped[int] = mapped_column(Integer)
    fee_amount: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


Index('uq_active_remittance_order',RemittanceItem.order_id,unique=True,mssql_where=text('active = 1'),sqlite_where=text('active = 1'))


class Settlement(Base):
    __tablename__ = 'order_settlements'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('delivery_orders.id'), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(BigInteger)
    retained_fee: Mapped[int] = mapped_column(Integer, default=0)
    reference: Mapped[str] = mapped_column(Unicode(150))
    note: Mapped[str] = mapped_column(Unicode(500), default='')
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    created: Mapped[str] = mapped_column(String(40), default=now)


Index('uq_order_settlement_kind', Settlement.order_id, Settlement.kind, unique=True)


class NotificationRead(Base):
    __tablename__ = 'notification_reads'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey('order_events.id'), primary_key=True)


class Plan(Base):
    __tablename__ = 'delivery_plans'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    shipper_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(30), default='planned')
    data: Mapped[str] = mapped_column(UnicodeText)
    created: Mapped[str] = mapped_column(String(40), default=now)
    updated: Mapped[str] = mapped_column(String(40), default=now)


class PlanOrder(Base):
    __tablename__ = 'plan_orders'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey('delivery_plans.id'), index=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('delivery_orders.id'), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


Index('uq_order_active_plan', PlanOrder.order_id, unique=True,
      mssql_where=text('active = 1'), sqlite_where=text('active = 1'))


class Event(Base):
    __tablename__ = 'order_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey('delivery_orders.id'), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(Unicode(500))
    created: Mapped[str] = mapped_column(String(40), default=now)


def connect(test_url=None):
    if test_url:
        engine = create_engine(test_url, connect_args={'check_same_thread': False} if test_url.startswith('sqlite') else {}, pool_pre_ping=True)
    else:
        # No implicit SQLite fallback. All application data lives in SQL Server.
        connection = os.environ.get('SQLSERVER_CONNECTION_STRING')
        if not connection:
            server = os.environ.get('SQLSERVER_SERVER', r'.\SQLEXPRESS')
            database = os.environ.get('SQLSERVER_DATABASE', 'GiaoGonShipper')
            driver = os.environ.get('SQLSERVER_DRIVER', 'ODBC Driver 17 for SQL Server')
            connection = f'DRIVER={{{driver}}};SERVER={server};DATABASE={database};Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=8;'
        engine = create_engine(URL.create('mssql+pyodbc', query={'odbc_connect': connection}), pool_pre_ping=True)
    # Additive migration for existing installations; never overwrite old orders.
    if inspect(engine).has_table('delivery_orders'):
        if 'created_by' not in {c['name'] for c in inspect(engine).get_columns('delivery_orders')}:
            with engine.begin() as c:
                if engine.dialect.name == 'mssql':
                    c.execute(text('ALTER TABLE delivery_orders ADD created_by VARCHAR(36) NULL REFERENCES users(id)'))
                else:
                    c.execute(text('ALTER TABLE delivery_orders ADD created_by VARCHAR(36) NULL REFERENCES users(id)'))
                c.execute(text('CREATE INDEX ix_delivery_orders_created_by ON delivery_orders(created_by)'))
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
