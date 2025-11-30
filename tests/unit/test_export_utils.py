from malla.utils.export_utils import (
    generate_csv,
    generate_json,
    get_content_type,
    get_export_filename,
)


def test_get_export_filename():
    filename = get_export_filename("packets", "csv")
    assert filename.startswith("malla_packets_")
    assert filename.endswith(".csv")

    filename = get_export_filename("nodes", "json")
    assert filename.startswith("malla_nodes_")
    assert filename.endswith(".json")


def test_get_content_type():
    assert get_content_type("csv") == "text/csv"
    assert get_content_type("json") == "application/json"
    assert get_content_type("xml") == "text/plain"  # Default


def test_generate_csv():
    data = [
        {"id": 1, "name": "Node 1", "timestamp": 1600000000},
        {"id": 2, "name": "Node 2", "timestamp": 1600000060},
    ]
    csv_output = generate_csv(data)
    assert "id,name,timestamp" in csv_output
    # Expect UTC ISO format
    assert "1,Node 1,2020-09-13T12:26:40+00:00" in csv_output
    assert "2,Node 2,2020-09-13T12:27:40+00:00" in csv_output


def test_generate_json():
    data = [
        {"id": 1, "name": "Node 1"},
        {"id": 2, "name": "Node 2"},
    ]
    json_output = generate_json(data)
    assert '"id": 1' in json_output
    assert '"name": "Node 1"' in json_output
    # JSON output is a list, so no "count" field
    assert '"id": 2' in json_output
