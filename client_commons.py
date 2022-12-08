import socket
import threading
import time
import random

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

WINDOW_SIZE = 5
RETRY_COUNT = 5
TIMEOUT = 1
MAX_FRAGMENT_SIZE = 1466
KEEP_ALIVE_TIMEOUT = 10
KEEP_ALIVE_SEND_PERIODIC = 5


class ClientCommons:
    conn: socket.socket
    isConnected = False
    ack_lock = False
    init_success = False
    swapping = False
    lastAlive = 0
    client = None

    def __init__(self):
        self.conn = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.conn.settimeout(1)

    def loop(self):
        pass

    def dispatch_message(self, host, msg_type, fragment, data):
        pass

    def dispatch_corrupted(self, host, msg_type, fragment):
        pass

    def await_response(self, packet):
        self.ack_lock = True
        send_time = 0
        retries = RETRY_COUNT
        while self.ack_lock:
            if retries == 0:
                return False
            if (time.time() - send_time) > TIMEOUT:
                send_time = time.time()
                self.conn.sendto(packet, self.client)
                retries -= 1
        return True

    def data_handler(self):
        print("Starting data handler job")
        while True:
            try:
                pair = self.conn.recvfrom(1472)
                data = pair[0]
                msg_type = data[0]
                fragment = (data[1] << 16) + (data[2] << 8) + data[3]
                if not self.check_corrupted(data):
                    print(f"Corrupted data detected {fragment}")
                    threading.Thread(target=self.dispatch_corrupted, args=(self.client, msg_type, fragment,)).start()
                else:
                    data = data[4: len(data) - 2]
                    threading.Thread(target=self.dispatch_message, args=(pair[1], msg_type, fragment, data,)).start()
            except socket.timeout:
                pass
            except OSError:
                print("Terminating data handler job")
                break

    def hard_terminate(self):
        print(f"Connection was terminated")
        self.isConnected = False
        self.conn.close()

    def soft_terminate(self):
        if self.await_response(self.build_packet(TYPE_TERMINATE_CONN)):
            self.hard_terminate()
            return
        print("Could not end connection due to client not responding.")

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

    def build_packet(self, msg_type, fragment=0, data: bytes = None, simulate_error=False):
        packet = bytearray()
        packet.append(msg_type)
        packet.append(fragment >> 16)
        packet.append((fragment >> 8) & 0xFF)
        packet.append(fragment & 0xFF)
        if data:
            for byte in data:
                packet.append(byte)
        crc = self.crc16(packet)
        if simulate_error:
            rand_data = random.randrange(4, len(data) + 3)
            packet[rand_data] = random.randrange(255)
        packet.append(crc >> 8)
        packet.append(crc & 0xFF)
        return packet

    def __keep_alive(self):
        print("Starting keep alive job")
        last_sent_millis = time.time()
        while self.isConnected:
            if time.time() - last_sent_millis > KEEP_ALIVE_SEND_PERIODIC:
                self.conn.sendto(self.build_packet(TYPE_ALIVE_MESSAGE), self.client)
                last_sent_millis = time.time()
            if (time.time() - self.lastAlive) > KEEP_ALIVE_TIMEOUT:
                self.hard_terminate()
        print("Terminating keep alive job")

    def start_keep_alive(self):
        self.lastAlive = time.time()
        threading.Thread(target=self.__keep_alive).start()

    def check_corrupted(self, data):
        crc_data = data[len(data) - 2:]
        crc = (crc_data[0] << 8) + crc_data[1]
        return self.crc16(data[:len(data) - 2]) == crc
