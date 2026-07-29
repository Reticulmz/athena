---
name: protocol-reverse-engineering
description: Master network protocol reverse engineering including packet analysis, protocol dissection, and custom protocol documentation. Use when analyzing network traffic, understanding proprietary protocols, or debugging network communication.
---

# Protocol Reverse Engineering

Comprehensive techniques for capturing, analyzing, and documenting network protocols for security research, interoperability, and debugging.

## Traffic Capture

### Wireshark Capture

```bash
# Capture on specific interface
wireshark -i eth0 -k

# Capture with filter
wireshark -i eth0 -k -f "port 443"

# Capture to file
tshark -i eth0 -w capture.pcap

# Ring buffer capture (rotate files)
tshark -i eth0 -b filesize:100000 -b files:10 -w capture.pcap
```

### tcpdump Capture

```bash
# Basic capture
tcpdump -i eth0 -w capture.pcap

# With filter
tcpdump -i eth0 port 8080 -w capture.pcap

# Capture specific bytes
tcpdump -i eth0 -s 0 -w capture.pcap  # Full packet

# Real-time display
tcpdump -i eth0 -X port 80
```

### Man-in-the-Middle Capture

```bash
# mitmproxy for HTTP/HTTPS
mitmproxy --mode transparent -p 8080

# SSL/TLS interception
mitmproxy --mode transparent --ssl-insecure

# Dump to file
mitmdump -w traffic.mitm

# Burp Suite
# Configure browser proxy to 127.0.0.1:8080
```

## Protocol Analysis

### Wireshark Analysis

```text
# Display filters
tcp.port == 8080
http.request.method == "POST"
ip.addr == 192.168.1.1
tcp.flags.syn == 1 && tcp.flags.ack == 0
frame contains "password"

# Following streams
Right-click > Follow > TCP Stream
Right-click > Follow > HTTP Stream

# Export objects
File > Export Objects > HTTP

# Decryption
Edit > Preferences > Protocols > TLS
  - (Pre)-Master-Secret log filename
  - RSA keys list
```

### tshark Analysis

```bash
# Extract specific fields
tshark -r capture.pcap -T fields -e ip.src -e ip.dst -e tcp.port

# Statistics
tshark -r capture.pcap -q -z conv,tcp
tshark -r capture.pcap -q -z endpoints,ip

# Filter and extract
tshark -r capture.pcap -Y "http" -T json > http_traffic.json

# Protocol hierarchy
tshark -r capture.pcap -q -z io,phs
```

### Scapy for Custom Analysis

```python
from scapy.all import *

# Read pcap
packets = rdpcap("capture.pcap")

# Analyze packets
for pkt in packets:
    if pkt.haslayer(TCP):
        print(f"Src: {pkt[IP].src}:{pkt[TCP].sport}")
        print(f"Dst: {pkt[IP].dst}:{pkt[TCP].dport}")
        if pkt.haslayer(Raw):
            print(f"Data: {pkt[Raw].load[:50]}")

# Filter packets
http_packets = [p for p in packets if p.haslayer(TCP)
                and (p[TCP].sport == 80 or p[TCP].dport == 80)]

# Create custom packets
pkt = IP(dst="target")/TCP(dport=80)/Raw(load="GET / HTTP/1.1\r\n")
send(pkt)
```

## Protocol Identification

### Common Protocol Signatures

```text
HTTP        - "HTTP/1." or "GET " or "POST " at start
TLS/SSL     - 0x16 0x03 (record layer)
DNS         - UDP port 53, specific header format
SMB         - 0xFF 0x53 0x4D 0x42 ("SMB" signature)
SSH         - "SSH-2.0" banner
FTP         - "220 " response, "USER " command
SMTP        - "220 " banner, "EHLO" command
MySQL       - 0x00 length prefix, protocol version
PostgreSQL  - 0x00 0x00 0x00 startup length
Redis       - "*" RESP array prefix
MongoDB     - BSON documents with specific header
```

### Protocol Header Patterns

```text
+--------+--------+--------+--------+
|  Magic number / Signature         |
+--------+--------+--------+--------+
|  Version       |  Flags          |
+--------+--------+--------+--------+
|  Length        |  Message Type   |
+--------+--------+--------+--------+
|  Sequence Number / Session ID     |
+--------+--------+--------+--------+
|  Payload...                       |
+--------+--------+--------+--------+
```

## Binary Protocol Analysis

### Structure Identification

```c
// Common patterns in binary protocols

// Length-prefixed message
struct Message {
    uint32_t length;      // Payload length in bytes
    uint16_t msg_type;    // Message type identifier
    uint8_t  flags;       // Flags/options
    uint8_t  reserved;    // Padding/alignment
    uint8_t  payload[];   // Variable-length payload
};

// Type-Length-Value (TLV)
struct TLV {
    uint8_t  type;        // Field type
    uint16_t length;      // Field length
    uint8_t  value[];     // Field data
};

// Fixed header + variable payload
struct Packet {
    uint8_t  magic[4];    // "ABCD" signature
    uint32_t version;
    uint32_t payload_len;
    uint32_t checksum;    // CRC32 or similar
    uint8_t  payload[];
};
```

### Python Protocol Parser

```python
import struct
from dataclasses import dataclass

HEADER_FORMAT = ">4sHHI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

@dataclass
class MessageHeader:
    magic: bytes
    version: int
    msg_type: int
    length: int

    @classmethod
    def from_bytes(cls, data: bytes):
        if len(data) < HEADER_SIZE:
            raise ValueError("Truncated message header")

        magic, version, msg_type, length = struct.unpack(
            HEADER_FORMAT, data[:HEADER_SIZE]
        )
        return cls(magic, version, msg_type, length)

def parse_messages(data: bytes):
    offset = 0
    messages = []

    while offset < len(data):
        header = MessageHeader.from_bytes(data[offset:])
        payload_start = offset + HEADER_SIZE
        message_end = payload_start + header.length
        if message_end > len(data):
            raise ValueError("Declared payload length exceeds available data")

        payload = data[payload_start:message_end]
        messages.append((header, payload))
        offset = message_end

    return messages

# Parse TLV structure
def parse_tlv(data: bytes):
    fields = []
    offset = 0

    while offset < len(data):
        if len(data) - offset < 3:
            raise ValueError("Truncated TLV header")

        field_type = data[offset]
        length = struct.unpack(">H", data[offset+1:offset+3])[0]
        value_start = offset + 3
        field_end = value_start + length
        if field_end > len(data):
            raise ValueError("Declared TLV length exceeds available data")

        value = data[value_start:field_end]
        fields.append((field_type, value))
        offset = field_end

    return fields
```

### Hex Dump Analysis

```python
def hexdump(data: bytes, width: int = 16):
    """Format binary data as hex dump."""
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i+width]
        hex_part = ' '.join(f'{b:02x}' for b in chunk)
        ascii_part = ''.join(
            chr(b) if 32 <= b < 127 else '.'
            for b in chunk
        )
        lines.append(f'{i:08x}  {hex_part:<{width*3}}  {ascii_part}')
    return '\n'.join(lines)

# Example output:
# 00000000  48 54 54 50 2f 31 2e 31  20 32 30 30 20 4f 4b 0d  HTTP/1.1 200 OK.
# 00000010  0a 43 6f 6e 74 65 6e 74  2d 54 79 70 65 3a 20 74  .Content-Type: t
```

## Encryption Analysis

### Identifying Encryption

```python
# Entropy analysis - high entropy suggests encryption/compression
import math
from collections import Counter

def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counter = Counter(data)
    probs = [count / len(data) for count in counter.values()]
    return -sum(p * math.log2(p) for p in probs)

# Entropy thresholds:
# < 6.0: Likely plaintext or structured data
# 6.0-7.5: Possibly compressed
# > 7.5: Likely encrypted or random

# Common encryption indicators
# - High, uniform entropy
# - No obvious structure or patterns
# - Length often multiple of block size (16 for AES)
# - Possible IV at start (16 bytes for AES-CBC)
```

### TLS Analysis

```bash
# Extract TLS metadata
tshark -r capture.pcap -Y "ssl.handshake" \
    -T fields -e ip.src -e ssl.handshake.ciphersuite

# JA3 fingerprinting (client)
tshark -r capture.pcap -Y "ssl.handshake.type == 1" \
    -T fields -e ssl.handshake.ja3

# JA3S fingerprinting (server)
tshark -r capture.pcap -Y "ssl.handshake.type == 2" \
    -T fields -e ssl.handshake.ja3s

# Certificate extraction
tshark -r capture.pcap -Y "ssl.handshake.certificate" \
    -T fields -e x509sat.printableString
```

### Decryption Approaches

```bash
# Pre-master secret log (browser)
export SSLKEYLOGFILE=/tmp/keys.log

# Configure Wireshark
# Edit > Preferences > Protocols > TLS
# (Pre)-Master-Secret log filename: /tmp/keys.log

# Decrypt with private key (if available)
# Only works for RSA key exchange
# Edit > Preferences > Protocols > TLS > RSA keys list
```

## Custom Protocol Documentation

### Protocol Specification Template

````markdown
# Protocol Name Specification

## Overview

Brief description of protocol purpose and design.

## Transport

- Layer: TCP/UDP
- Port: XXXX
- Encryption: TLS 1.2+

## Message Format

### Header (12 bytes)

| Offset | Size | Field   | Description             |
| ------ | ---- | ------- | ----------------------- |
| 0      | 4    | Magic   | 0x50524F54 ("PROT")     |
| 4      | 2    | Version | Protocol version (1)    |
| 6      | 2    | Type    | Message type identifier |
| 8      | 4    | Length  | Payload length in bytes |

### Message Types

| Type | Name      | Description            |
| ---- | --------- | ---------------------- |
| 0x01 | HELLO     | Connection initiation  |
| 0x02 | HELLO_ACK | Connection accepted    |
| 0x03 | DATA      | Application data       |
| 0x04 | CLOSE     | Connection termination |

### Type 0x01: HELLO

| Offset | Size | Field      | Description              |
| ------ | ---- | ---------- | ------------------------ |
| 0      | 4    | ClientID   | Unique client identifier |
| 4      | 2    | Flags      | Connection flags         |
| 6      | var  | Extensions | TLV-encoded extensions   |

## State Machine
```text

[INIT] --HELLO--> [WAIT_ACK] --HELLO_ACK--> [CONNECTED]
|
DATA/DATA
|
[CLOSED] <--CLOSE--+

```

## Examples
### Connection Establishment
```text

Client -> Server: HELLO (ClientID=0x12345678)
Server -> Client: HELLO_ACK (Status=OK)
Client -> Server: DATA (payload)

```
````

### Wireshark Dissector (Lua)

```lua
-- custom_protocol.lua
local proto = Proto("custom", "Custom Protocol")

-- Define fields
local f_magic = ProtoField.string("custom.magic", "Magic")
local f_version = ProtoField.uint16("custom.version", "Version")
local f_type = ProtoField.uint16("custom.type", "Type")
local f_length = ProtoField.uint32("custom.length", "Length")
local f_payload = ProtoField.bytes("custom.payload", "Payload")

proto.fields = { f_magic, f_version, f_type, f_length, f_payload }

-- Message type names
local msg_types = {
    [0x01] = "HELLO",
    [0x02] = "HELLO_ACK",
    [0x03] = "DATA",
    [0x04] = "CLOSE"
}

function proto.dissector(buffer, pinfo, tree)
    pinfo.cols.protocol = "CUSTOM"

    local subtree = tree:add(proto, buffer())
    local header_length = 12

    if buffer:len() < header_length then
        pinfo.cols.info = "Malformed: truncated header"
        return
    end

    -- Parse header
    subtree:add(f_magic, buffer(0, 4))
    subtree:add(f_version, buffer(4, 2))

    local msg_type = buffer(6, 2):uint()
    subtree:add(f_type, buffer(6, 2)):append_text(
        " (" .. (msg_types[msg_type] or "Unknown") .. ")"
    )

    local length = buffer(8, 4):uint()
    subtree:add(f_length, buffer(8, 4))

    if length > buffer:len() - header_length then
        pinfo.cols.info = "Malformed: payload length exceeds captured data"
        return
    end

    if length > 0 then
        subtree:add(f_payload, buffer(header_length, length))
    end
end

-- Register for TCP port
local tcp_table = DissectorTable.get("tcp.port")
tcp_table:add(8888, proto)
```

## Active Testing

### Fuzzing with Boofuzz

Warning: Protocol fuzzing can crash or corrupt targets. Run this example only against an explicitly authorized service in an isolated lab or sandbox.

```python
import os

from boofuzz import *

def get_authorized_target() -> tuple[str, int]:
    if os.environ.get("FUZZ_TARGET_AUTHORIZED") != "yes":
        raise RuntimeError(
            "Set FUZZ_TARGET_AUTHORIZED=yes only for an authorized lab target"
        )

    host = os.environ.get("FUZZ_TARGET_HOST")
    port_value = os.environ.get("FUZZ_TARGET_PORT")
    if not host or not port_value:
        raise RuntimeError("Set FUZZ_TARGET_HOST and FUZZ_TARGET_PORT")

    try:
        port = int(port_value)
    except ValueError as error:
        raise RuntimeError("FUZZ_TARGET_PORT must be an integer") from error

    if not 1 <= port <= 65535:
        raise RuntimeError("FUZZ_TARGET_PORT must be between 1 and 65535")
    return host, port

def main():
    target_host, target_port = get_authorized_target()
    session = Session(
        target=Target(
            connection=TCPSocketConnection(target_host, target_port)
        )
    )

    # Define protocol structure
    s_initialize("HELLO")
    s_static(b"\x50\x52\x4f\x54")  # Magic
    s_word(1, name="version")       # Version
    s_word(0x01, name="type")       # Type (HELLO)
    s_size("payload", length=4)     # Length field
    s_block_start("payload")
    s_dword(0x12345678, name="client_id")
    s_word(0, name="flags")
    s_block_end()

    session.connect(s_get("HELLO"))
    session.fuzz()

if __name__ == "__main__":
    main()
```

### Replay and Modification

```python
from scapy.all import *

# Replay captured traffic
packets = rdpcap("capture.pcap")
for pkt in packets:
    if pkt.haslayer(TCP) and pkt[TCP].dport == 8888:
        send(pkt)

# Modify and replay
for pkt in packets:
    if pkt.haslayer(Raw):
        # Modify payload
        original = pkt[Raw].load
        modified = original.replace(b"client", b"CLIENT")
        pkt[Raw].load = modified
        # Recalculate checksums
        del pkt[IP].chksum
        del pkt[TCP].chksum
        send(pkt)
```

## Best Practices

### Analysis Workflow

1. **Capture traffic**: Multiple sessions, different scenarios
2. **Identify boundaries**: Message start/end markers
3. **Map structure**: Fixed header, variable payload
4. **Identify fields**: Compare multiple samples
5. **Document format**: Create specification
6. **Validate understanding**: Implement parser/generator
7. **Test edge cases**: Fuzzing, boundary conditions

### Common Patterns to Look For

- Magic numbers/signatures at message start
- Version fields for compatibility
- Length fields (often before variable data)
- Type/opcode fields for message identification
- Sequence numbers for ordering
- Checksums/CRCs for integrity
- Timestamps for timing
- Session/connection identifiers
