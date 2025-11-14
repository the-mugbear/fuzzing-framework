"""
Test protocol plugin with auto-generated seeds

This demonstrates that seeds can be omitted and will be automatically
generated from the data_model definition. No manual binary crafting required!
"""

__version__ = "1.0.0"

# Data model defines message structure
# NOTE: No manual "seeds" array - they will be auto-generated!
data_model = {
    "name": "AutoTest",
    "description": "A test protocol with auto-generated seeds",
    "blocks": [
        {
            "name": "magic",
            "type": "bytes",
            "size": 4,
            "default": b"AUTO",
            "mutable": False,
        },
        {
            "name": "length",
            "type": "uint32",
            "endian": "big",
            "is_size_field": True,
            "size_of": "payload",
        },
        {
            "name": "command",
            "type": "uint8",
            "values": {
                0x01: "CONNECT",
                0x02: "SEND",
                0x03: "CLOSE",
            },
        },
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 512,
            "default": b"",
        },
    ],
    # Seeds will be auto-generated from the blocks above!
    # No need to manually craft binary data
}

# State model defines protocol state machine
state_model = {
    "initial_state": "INIT",
    "states": ["INIT", "CONNECTED", "READY", "CLOSED"],
    "transitions": [
        {
            "from": "INIT",
            "to": "CONNECTED",
            "trigger": "connect",
            "message_type": "CONNECT",
        },
        {
            "from": "CONNECTED",
            "to": "READY",
            "trigger": "send",
            "message_type": "SEND",
        },
        {
            "from": "READY",
            "to": "CLOSED",
            "trigger": "close",
            "message_type": "CLOSE",
        },
    ],
}


def validate_response(response: bytes) -> bool:
    """Optional validation function for response checking"""
    if len(response) < 4:
        return False

    # Check magic header
    if response[:4] != b"AUTO":
        return False

    return True
