"""
Test protocol with explicitly empty seeds array

This demonstrates that even with "seeds": [] defined, auto-generation
will kick in and create baseline seeds.
"""

__version__ = "1.0.0"

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
