from app.services.inventory_sync import build_inventory


def test_inventory_payload_omits_credentials_and_contains_runtime_state():
    payload = build_inventory(
        node_id="node-1",
        node_name="Shanghai child",
        version="0.1.0",
        hosts=[
            {
                "id": "host-1",
                "name": "web-01",
                "address": "10.0.0.10",
                "port": 22,
                "username": "root",
                "tags": ["production"],
                "is_local": True,
                "last_test_status": "success",
                "encrypted_password": "must-not-leak",
            }
        ],
    )

    assert payload["node"]["id"] == "node-1"
    assert payload["hosts"][0] == {
        "id": "host-1",
        "name": "web-01",
        "address": "10.0.0.10",
        "port": 22,
        "username": "root",
        "tags": ["production"],
        "is_local": True,
        "last_test_status": "success",
    }
    assert "password" not in str(payload)


def test_inventory_change_wakes_background_sync():
    from app.services.inventory_sync import InventorySynchronizer

    synchronizer = InventorySynchronizer(None, None)
    assert synchronizer.changed.is_set() is False

    synchronizer.notify_change()

    assert synchronizer.changed.is_set() is True
