"""
Repository classes for database operations.
Uses SQLAlchemy ORM for universal DB support.
"""

import logging
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_
from .connection import get_db_session
from .models import PacketHistory, NodeInfo  # You need to define these ORM models!

logger = logging.getLogger(__name__)

class PacketRepository:
    """Repository for packet operations."""

    @staticmethod
    def get_packets(limit=100, offset=0, filters=None, order_by="timestamp", order_dir="desc"):
        filters = filters or {}
        session = next(get_db_session())
        query = session.query(PacketHistory)

        # Example filtering
        if filters.get("from_node"):
            query = query.filter(PacketHistory.from_node_id == filters["from_node"])
        if filters.get("to_node"):
            query = query.filter(PacketHistory.to_node_id == filters["to_node"])
        if filters.get("min_rssi"):
            query = query.filter(PacketHistory.rssi >= filters["min_rssi"])
        if filters.get("max_rssi"):
            query = query.filter(PacketHistory.rssi <= filters["max_rssi"])

        # Sorting
        if order_by and hasattr(PacketHistory, order_by):
            col = getattr(PacketHistory, order_by)
            if order_dir.lower() == "desc":
                query = query.order_by(desc(col))
            else:
                query = query.order_by(col)

        total_count = query.count()
        packets = query.offset(offset).limit(limit).all()

        session.close()
        return {
            "packets": [p.to_dict() for p in packets],  # to_dict() method needs to be implemented on ORM models
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
        }

class NodeRepository:
    """Repository for node operations."""

    @staticmethod
    def get_nodes(limit=100, offset=0, order_by="last_updated", order_dir="desc"):
        session = next(get_db_session())
        query = session.query(NodeInfo)
        if order_by and hasattr(NodeInfo, order_by):
            col = getattr(NodeInfo, order_by)
            if order_dir.lower() == "desc":
                query = query.order_by(desc(col))
            else:
                query = query.order_by(col)
        total_count = query.count()
        nodes = query.offset(offset).limit(limit).all()
        session.close()
        return {
            "nodes": [n.to_dict() for n in nodes],  # to_dict() method needs to be implemented on ORM models
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
        }