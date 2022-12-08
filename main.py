import random

poly = 0x8005


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


def build_packet(msg_type, fragment, data: str, simulate_err=False):
    pkt = bytearray()
    pkt.append(msg_type)
    pkt.append(fragment >> 16)
    pkt.append((fragment >> 8) & 0xFF)
    pkt.append(fragment & 0xFF)
    for byte in data.encode():
        pkt.append(byte)
    crc = crc16(pkt)
    if simulate_err:
        rand_data = random.randrange(len(data))
        pkt[rand_data] = random.randrange(255)
    pkt.append(crc >> 8)
    pkt.append(crc & 0xFF)
    return pkt



# data = bytes([0x90, 0])
# crcVal = crc16(data)
# print(data)
# data = bytes([0x90, 0, crcVal & 0xFF, crcVal >> 8])
# print(data)
# print(crc16(data))

# print(crcVal)
# print(crc16("1234".encode() + crcVal.to_bytes(2, "little")))

# packet = build_packet(0, 0, "Fs")
packet2 = build_packet(0, 0, "", False)
# print(packet)
# print(crc16(packet))
#
# print(packet2)
# print(crc16(packet))

print(packet2)
crc_data = packet2[len(packet2)-2:]
crc = (crc_data[0] << 8) + crc_data[1]
print(crc)
print(crc16(packet2[:len(packet2)-2]) == crc)
