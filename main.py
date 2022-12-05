
poly = 0xA001


def crc16(data: bytes):
    crc = 0xFFFF
    for byte in data:
        crc = crc ^ byte
        for i in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def build_packet(msg_type, fragment, data: str):
    packet = bytearray()
    packet.append(msg_type << 4 + (fragment >> 12))
    packet.append(fragment & 0xFF)
    for byte in data.encode():
        packet.append(byte)
    crc = crc16(packet)
    packet.append(crc >> 8)
    packet.append(crc & 0x0F)
    return packet



data = bytes([0x43, 0, 0, 0x37, 0x31, 0x32, 0x33, 0x34])
crcVal = crc16(data)
print(data)
print(crcVal)
data = bytes([0x43, 0, 0, 0x37, 0x31, 0x32, 0x33, 0x34, crcVal & 0xFF, crcVal >> 8])
print(data)
print(crc16(data))

# print(crcVal)
# print(crc16("1234".encode() + crcVal.to_bytes(2, "little")))
