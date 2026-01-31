"""
Protocol Plugins Package

This package contains protocol plugins organized into three categories:

standard/
    Production-ready plugins for common network protocols.
    Use these directly or as reference implementations.
    Includes: DNS, MQTT, Modbus/TCP, TFTP, NTP, CoAP, IPv4

examples/
    Learning-focused plugins demonstrating framework features.
    Copy these as templates when building your own protocols.
    Includes:
    - minimal_tcp.py   - Start here for TCP protocols
    - minimal_udp.py   - Start here for UDP protocols
    - feature_reference.py - Comprehensive feature showcase
    - orchestrated.py  - Multi-stage protocols with auth
    - stateful.py      - Complex state machines
    - field_types.py   - Quick copy-paste reference

custom/
    Place your own custom protocol plugins here.
    They will be auto-discovered on restart.

See docs/PROTOCOL_PLUGIN_GUIDE.md for detailed documentation.
"""
