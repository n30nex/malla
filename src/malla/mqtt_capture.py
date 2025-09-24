# ... other imports ...
from src.malla.database.connection import get_db_session
from src.malla.database.models import PacketHistory, NodeInfo

def save_packet_to_db(packet_data):
    session = next(get_db_session())
    packet = PacketHistory(
        timestamp=packet_data.get("timestamp"),
        topic=packet_data.get("topic"),
        from_node_id=packet_data.get("from_node_id"),
        to_node_id=packet_data.get("to_node_id"),
        portnum=packet_data.get("portnum"),
        portnum_name=packet_data.get("portnum_name"),
        gateway_id=packet_data.get("gateway_id"),
        channel_id=packet_data.get("channel_id"),
        mesh_packet_id=packet_data.get("mesh_packet_id"),
        rssi=packet_data.get("rssi"),
        snr=packet_data.get("snr"),
        hop_limit=packet_data.get("hop_limit"),
        hop_start=packet_data.get("hop_start"),
        payload_length=packet_data.get("payload_length"),
        raw_payload=packet_data.get("raw_payload"),
        processed_successfully=packet_data.get("processed_successfully", True),
        message_type=packet_data.get("message_type"),
        raw_service_envelope=packet_data.get("raw_service_envelope"),
        parsing_error=packet_data.get("parsing_error"),
    )
    session.add(packet)
    session.commit()
    session.close()