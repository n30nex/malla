from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class PacketHistory(Base):
    __tablename__ = "packet_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(Float, nullable=False)
    topic = Column(String, nullable=False)
    from_node_id = Column(Integer)
    to_node_id = Column(Integer)
    portnum = Column(Integer)
    portnum_name = Column(String)
    gateway_id = Column(String)
    channel_id = Column(String)
    mesh_packet_id = Column(Integer)
    rssi = Column(Integer)
    snr = Column(Float)
    hop_limit = Column(Integer)
    hop_start = Column(Integer)
    payload_length = Column(Integer)
    raw_payload = Column(String)
    processed_successfully = Column(Boolean, default=True)
    message_type = Column(String)
    raw_service_envelope = Column(String)
    parsing_error = Column(String)

    def to_dict(self):
        # Return a dict for API responses
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class NodeInfo(Base):
    __tablename__ = "node_info"

    node_id = Column(Integer, primary_key=True)
    hex_id = Column(String)
    long_name = Column(String)
    short_name = Column(String)
    hw_model = Column(String)
    role = Column(String)
    primary_channel = Column(String)
    is_licensed = Column(Boolean)
    mac_address = Column(String)
    first_seen = Column(Float, nullable=False, default=lambda: datetime.utcnow().timestamp())
    last_updated = Column(Float, nullable=False, default=lambda: datetime.utcnow().timestamp())

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}