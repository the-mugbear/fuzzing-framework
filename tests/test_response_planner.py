from core.engine.protocol_parser import ProtocolParser
from core.engine.response_planner import ResponsePlanner


REQUEST_MODEL = {
    "blocks": [
        {"name": "magic", "type": "bytes", "size": 4, "default": b"PLAN"},
        {"name": "command", "type": "uint8", "default": 0x01},
        {"name": "token", "type": "uint32", "default": 0},
    ]
}

RESPONSE_MODEL = {
    "blocks": [
        {"name": "magic", "type": "bytes", "size": 4, "default": b"PLAN"},
        {"name": "status", "type": "uint8", "default": 0x01},
        {"name": "session_token", "type": "uint32", "default": 0},
    ]
}


def build_response(status: int, token: int) -> bytes:
    parser = ProtocolParser(RESPONSE_MODEL)
    return parser.serialize(
        {
            "magic": b"PLAN",
            "status": status,
            "session_token": token,
        }
    )


def test_response_planner_builds_followup_payload():
    handlers = [
        {
            "name": "assign_token",
            "match": {"status": 0x01},
            "set_fields": {
                "command": 0x02,
                "token": {"copy_from_response": "session_token"},
            },
        }
    ]
    planner = ResponsePlanner(REQUEST_MODEL, RESPONSE_MODEL, handlers)

    response = build_response(status=0x01, token=0xDEADBEEF)
    followups = planner.plan(response)

    assert followups, "Expected follow-up request to be generated"
    request_parser = ProtocolParser(REQUEST_MODEL)
    parsed_followup = request_parser.parse(followups[0]["payload"])
    assert parsed_followup["command"] == 0x02
    assert parsed_followup["token"] == 0xDEADBEEF


def test_response_planner_skips_non_matching_responses():
    handlers = [
        {
            "name": "assign_token",
            "match": {"status": 0x02},
            "set_fields": {"command": 0x03},
        }
    ]
    planner = ResponsePlanner(REQUEST_MODEL, RESPONSE_MODEL, handlers)

    response = build_response(status=0x01, token=0x11111111)
    followups = planner.plan(response)

    assert followups == []
