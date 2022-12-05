import socket
import threading
import time


TYPE_START_CONN = 0b0000
TYPE_TERMINATE_CONN = 0b0001
TYPE_SWAP_MODE = 0b0010
TYPE_ALIVE_MESSAGE = 0b0011
TYPE_FRAGMENT_REPEAT = 0b0100
TYPE_DATA_TRANSMISSION_COMPLETE = 0b0101
TYPE_DATA_FRAGMENT = 0b0110
TYPE_PREPARE_TRANSMISSION = 0b0111
TYPE_FRAGMENT_ACK = 0b1000
TYPE_ACTION_ACK = 0b1001


class ClientCommons:

    conn: socket.socket
    isConnected: bool
    ack_lock: bool
    lastAlive: time
    client: ()

    def __init__(self):
        self.isConnected = False
        self.ack_lock = False
        self.lastAlive = 0
        self.conn = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.conn.settimeout(1)

    def loop(self):
        pass

    def dispatch_message(self, host, msg_type, fragment, data):
        pass

    def data_handler(self):
        print("Starting data handler job")
        while True:
            try:
                pair = self.conn.recvfrom(1472)
                data = pair[0]
                if self.check_corrupted(data):
                    print(f"Corrupted data detected {data}")
                else:
                    msg_type = data[0] >> 4
                    fragment = (data[0] & 0xF) + data[1]
                    data = data[2: len(data) - 2]
                    self.dispatch_message(pair[1], msg_type, fragment, data)
            except socket.timeout:
                pass
            except OSError:
                print("Terminating data handler job")
                break

    def check_corrupted(self, data):
        return self.crc16(data) == 0

    def hard_terminate(self):
        self.isConnected = False
        self.conn.close()

    def soft_terminate(self):
        self.conn.sendto(self.build_packet(TYPE_TERMINATE_CONN), self.client)
        self.ack_lock = True
        while self.ack_lock and self.isConnected:
            self.hard_terminate()

    @staticmethod
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

    def build_packet(self, msg_type, fragment=0, data: bytes = None):
        packet = bytearray()
        packet.append(msg_type << 4 + (fragment >> 12))
        packet.append(fragment & 0xFF)
        if data:
            for byte in data:
                packet.append(byte)
        crc = self.crc16(packet)
        packet.append(crc >> 8)
        packet.append(crc & 0xFF)
        return packet

    def __keep_alive(self):
        print("Starting keep alive job")
        while self.isConnected:
            time.sleep(5)
            if self.isConnected:
                self.conn.sendto(self.build_packet(TYPE_ALIVE_MESSAGE), self.client)
                if (time.time() - self.lastAlive) > 10:
                    self.hard_terminate()
        print("Terminating keep alive job")

    def start_keep_alive(self):
        self.lastAlive = time.time()
        threading.Thread(target=self.__keep_alive).start()
