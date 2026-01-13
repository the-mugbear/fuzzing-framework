"""
Empty-seeds test protocol.

- Purpose: Demonstrates seed synthesis when seeds are explicitly empty.
- Transport: TCP.
- Includes: Small fixed header and payload.
"""

__version__ = "1.0.0"
transport = "tcp"

data_model = {
    "name": "EmptySeedsTest",
    "description": "Protocol with empty seeds array - should auto-generate",
    "blocks": [
        {
            "name": "header",
            "type": "bytes",
            "size": 2,
            "default": b"ES",
            "mutable": False,
        },
        {
            "name": "type",
            "type": "uint8",
            "values": {
                0xAA: "PING",
                0xBB: "PONG",
            },
        },
    ],
    # Explicitly empty - should trigger auto-generation
    "seeds": [],
}

state_model = {
    "initial_state": "IDLE",
    "states": ["IDLE", "ACTIVE"],
    "transitions": [],
}
