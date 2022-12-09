import socket
import threading
import time
import random
from os import path


# DEFINE CONSTANTS
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
TIMEOUT = 2
MAX_FRAGMENT_SIZE = 1467
KEEP_ALIVE_TIMEOUT = 10
KEEP_ALIVE_SEND_PERIODIC = 5
MAX_DATA_PAYLOAD = 2_097_152

# DEFINE HELPER VARIABLES
is_connected = False
ack_lock = False
init_success = False
swapping = False
last_alive = 0
client = None
is_sender = False
terminating = False
isText = False
file_path = ""
fragment_size = MAX_FRAGMENT_SIZE
free_window = WINDOW_SIZE
connecting = False
repeat_indexes = []
fragmented_data = []
window_index = 0


# DEFINE SOCKET
conn = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
conn.settimeout(1)


def main():
    global is_sender
    print("Select mode:\nr - Receiver\ns - Sender")
    data = input()
    if (data == "r") or data == "s":
        threading.Thread(target=data_handler).start()
        if data == "r":
            is_sender = False
            init_receiver()
        elif data == "s":
            is_sender = True
            init_sender()
    else:
        print("Invalid option, terminating.")
        exit(0)
    loop()


def loop():
    global is_connected
    global is_sender
    global swapping
    try:
        while True:
            if is_sender:
                print("Type END to end")
                print("Type SWAP to swap roles")
                print("Type TXT to send text messages")
                print("Type FILE to send file")
                print("Type OFFSET to set fragment size")
                data = input()
                if data == "END":
                    soft_terminate()
                    break
                if data == "TXT":
                    text_transfer()
                if data == "FILE":
                    file_transfer()
                if data == "SWAP":
                    if await_response(build_packet(TYPE_SWAP_MODE)):
                        swapping = True
                    else:
                        print("Could not swap. Client did not respond")
                if data == "OFFSET":
                    change_offset()
            elif terminating:
                break
            if swapping:
                is_sender = not is_sender
                swapping = False
                print(f"SWAPPING TO MODE {'SENDER' if is_sender else 'RECEIVER'}")
        hard_terminate()
    except KeyboardInterrupt:
        exit(0)
    except:
        hard_terminate()


def init_receiver():
    global conn
    ip = socket.gethostbyname(socket.gethostname())
    while True:
        print("Enter port number. Press Enter to auto assign.")
        port_str = input()
        if len(port_str) > 0:
            try:
                port = int(port_str)
                if port > 65535:
                    print("Invalid number entered, try again")
                else:
                    conn.bind((ip, port))
                    break
            except Exception:
                print("Invalid number entered, try again")
        else:
            conn.bind((ip, 0))
            break
    print(f"Server active, ip: {conn.getsockname()[0]} {conn.getsockname()[1]}")
    return True


def init_sender():
    global conn
    while True:
        print("Ip addr: ", end='')
        ip_addr = input()
        print("Port: ", end='')
        port = int(input())
        if not connect(ip_addr, port):
            print("Failed to connect, type n to terminate")
            data = input()
            if data == 'n':
                return False
        else:
            return True


# CALCULATE CRC16
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


# BUILD PACKET WITH TYPE, FRAGMENT, DATA AND CRC
def build_packet(msg_type, fragment=0, data: bytes = None, simulate_error=False):
    packet = bytearray()
    packet.append((msg_type << 4) + (fragment >> 16))
    packet.append((fragment >> 8) & 0xFF)
    packet.append(fragment & 0xFF)
    if data:
        for byte in data:
            packet.append(byte)
    crc = crc16(packet)
    if simulate_error:
        rand_data = random.randrange(3, len(data) + 2)
        packet[rand_data] = random.randrange(255)
    packet.append(crc >> 8)
    packet.append(crc & 0xFF)
    return packet


# HANDLE INCOMING DATA, THIS WORKS ON SEPARATE THREAD
def data_handler():
    print("Starting data handler job")
    while True:
        try:
            pair = conn.recvfrom(1472)
            data = pair[0]
            msg_type = data[0] >> 4
            fragment = ((data[0] & 0x0F) << 16) + (data[1] << 8) + data[2]
            if not check_corrupted(data):
                print(f"Corrupted data detected {fragment}")
                threading.Thread(target=dispatch_corrupted, args=(msg_type, fragment)).start()
            else:
                data = data[3: len(data) - 2]
                threading.Thread(target=dispatch_message, args=(pair[1], msg_type, fragment, data)).start()
        except socket.timeout:
            pass
        except OSError:
            print("Terminating data handler job")
            break


def await_response(packet):
    global ack_lock
    global conn
    global client
    ack_lock = True
    send_time = 0
    retries = RETRY_COUNT
    while ack_lock:
        if retries == 0:
            return False
        if (time.time() - send_time) > TIMEOUT:
            send_time = time.time()
            conn.sendto(packet, client)
            retries -= 1
    return True


def hard_terminate():
    print("CONNECTION WAS TERMINATED")
    global is_connected
    global terminating
    terminating = True
    is_connected = False
    conn.close()


def soft_terminate():
    if await_response(build_packet(TYPE_TERMINATE_CONN)):
        hard_terminate()
    else:
        print("Could not end connection due to client not responding.")


def keep_alive():
    global last_alive
    last_alive = time.time()
    last_sent_millis = time.time()
    print("Starting keep alive job")
    while is_connected:
        if time.time() - last_sent_millis > KEEP_ALIVE_SEND_PERIODIC:
            conn.sendto(build_packet(TYPE_ALIVE_MESSAGE), client)
            last_sent_millis = time.time()
        if (time.time() - last_alive) > KEEP_ALIVE_TIMEOUT:
            print("Keep alive exceeded, terminating.")
            hard_terminate()
    print("Terminating keep alive job")


def check_corrupted(data):
    crc_data = data[len(data) - 2:]
    crc = (crc_data[0] << 8) + crc_data[1]
    return crc16(data[:len(data) - 2]) == crc


def accept_connection(host):
    print(f"HOST CONNECTED: {host}")
    global client
    global is_connected
    conn.sendto(build_packet(TYPE_ACTION_ACK), host)
    client = host
    is_connected = True
    threading.Thread(target=keep_alive).start()


def build_data(fragment, data: bytes):
    print(f"RECEIVED FRAGMENT {fragment}")
    fragmented_data[fragment] = data
    conn.sendto(build_packet(TYPE_FRAGMENT_ACK, fragment), client)


def prepare_transmission(fragments, data: bytes):
    global isText
    global fragmented_data
    global file_path
    parsed_data = data.decode()
    isText = parsed_data[0] == 'T'
    fragmented_data = [None] * fragments
    if not isText:
        filename = parsed_data[1:]
        while True:
            print(f"Enter path for receiving file {filename}")
            file_path = input()
            if path.isdir(file_path) and path.exists(file_path):
                break
            print("Invalid path. Please reenter")
        if not file_path.endswith('/') or file_path.endswith('\\'):
            delim = '/' if file_path.count('/') else '\\'
            file_path += delim
        file_path += filename
    conn.sendto(build_packet(TYPE_ACTION_ACK), client)


def finish_transfer():
    print(f"FINISHING TRANSFER")
    conn.sendto(build_packet(TYPE_ACTION_ACK), client)
    if isText:
        print("Got text message: ", end='')
        for fragment in fragmented_data:
            for char in fragment:
                print(chr(char), end='')
    else:
        file = open(file_path, 'wb')
        for fragment in fragmented_data:
            file.write(fragment)
        file.close()
        print(f"Saved file to {file_path}")
    print()


def dispatch_message(host, msg_type, fragment, data):
    global last_alive
    global swapping
    global ack_lock
    global is_connected
    global connecting
    global free_window
    if msg_type == TYPE_ACTION_ACK:
        ack_lock = False
        if connecting:
            is_connected = True
            connecting = False
    if msg_type == TYPE_ALIVE_MESSAGE:
        last_alive = time.time()
    if msg_type == TYPE_START_CONN:
        if not client:
            accept_connection(host)
    if msg_type == TYPE_TERMINATE_CONN:
        conn.sendto(build_packet(TYPE_ACTION_ACK), client)
        hard_terminate()
    if msg_type == TYPE_FRAGMENT_ACK:
        free_window += 1
        fragmented_data[fragment]["ack_state"] = True
        print(f"ACKED {fragment}")
    if msg_type == TYPE_FRAGMENT_REPEAT:
        repeat_indexes.append(fragment)
        free_window += 1
        print(f"REPEAT REQUESTED {fragment}")
    if msg_type == TYPE_PREPARE_TRANSMISSION:
        threading.Thread(target=prepare_transmission, args=(fragment, data)).start()
    if msg_type == TYPE_DATA_FRAGMENT:
        build_data(fragment, data)
    if msg_type == TYPE_DATA_TRANSMISSION_COMPLETE:
        finish_transfer()
    if msg_type == TYPE_SWAP_MODE:
        swapping = True
        conn.sendto(build_packet(TYPE_ACTION_ACK), client)


def dispatch_corrupted(msg_type, fragment):
    if not is_sender:
        if ((fragmented_data is not None) and (fragment < len(fragmented_data))) and (msg_type == TYPE_DATA_FRAGMENT):
            conn.sendto(build_packet(TYPE_FRAGMENT_REPEAT, fragment), client)


def get_preferred_fragment():
    global window_index
    result: []
    if len(repeat_indexes) > 0:
        index = repeat_indexes[0]
        result = fragmented_data[index]
        repeat_indexes.remove(index)
    else:
        if window_index == len(fragmented_data):
            result = None
        else:
            result = fragmented_data[window_index]
            window_index += 1
    return result


def all_data_sent():
    if not ((window_index == len(fragmented_data)) and len(repeat_indexes) == 0):
        return False
    for fragment in fragmented_data:
        if not fragment["ack_state"]:
            return False
    return True


def check_timeouts():
    global free_window
    now = time.time()
    for i in range(0, window_index):
        if (not fragmented_data[i]["ack_state"]) and (now - fragmented_data[i]["sent_time"] > 5):
            fragmented_data[i]["sent_time"] = now
            free_window += 1
            repeat_indexes.append(i)


def send_bytes(data, start_payload):
    global window_index
    global ack_lock
    global free_window
    global fragmented_data
    if len(data) > MAX_DATA_PAYLOAD:
        print("Data payload is too large")
        return
    print("Do you want to simulate errors? y/N")
    str_input = input()
    errors = False
    if (str_input == 'Y') or (str_input == 'y'):
        errors = True
    index = 0
    fragmented_data = []
    for i in range(0, len(data), fragment_size):
        fragmented_data.append({
            "index": index,
            "data": data[i: i + fragment_size],
            "sent_time": 0.0,
            "ack_state": False,
            "simulate_error": False if (not errors) else bool(random.getrandbits(1))
        })
        index += 1
    window_index = 0
    ack_lock = True
    free_window = WINDOW_SIZE
    conn.sendto(build_packet(TYPE_PREPARE_TRANSMISSION, fragment=index, data=start_payload.encode()), client)
    while ack_lock:
        pass
    print("STARTING TRANSFER")
    while not all_data_sent():
        if free_window > 0:
            free_window -= 1
            fragment = get_preferred_fragment()
            if fragment is not None:
                print(f"SENDING {fragment['index']} corrupted: {fragment['simulate_error']}")
                conn.sendto(build_packet(TYPE_DATA_FRAGMENT, fragment["index"], fragment["data"], fragment["simulate_error"]), client)
                fragment["simulate_error"] = False
                fragment["sent_time"] = time.time()
        else:
            check_timeouts()
    if not await_response(build_packet(TYPE_DATA_TRANSMISSION_COMPLETE)):
        print("Could not finish transmission. Aborting")
    else:
        print("TRANSMISSION COMPLETED")


def text_transfer():
    print("Press ENTER to exit text transfer, otherwise type message to send")
    while True:
        text = input()
        if text == '':
            break
        send_bytes(text.encode(), "T")


def file_transfer():
    print("Enter file path to send")
    path = input()
    try:
        file = open(path, "rb")
        delim = '/' if path.__contains__('/') else '\\'
        split = file.name.split(delim)
        data = file.read()
        file.close()
        send_bytes(data, "F" + split[len(split) - 1])
    except FileNotFoundError:
        print("File not found")
    except Exception:
        print("Error reading file")


def connect(ip, conn_port):
    global client
    global connecting
    print("Connecting...")
    client = (ip, conn_port)
    connecting = True
    if not await_response(build_packet(TYPE_START_CONN)):
        print("Failed to connect")
        client = None
        return False
    print("Connected")
    threading.Thread(target=keep_alive).start()
    return True


def change_offset():
    global fragment_size
    print("Type int value of offset")
    while True:
        size_str = input()
        try:
            size = int(size_str)
            if size < 1:
                print("Cannot set offset. Offset has to be larger that 0.")
            elif size > MAX_FRAGMENT_SIZE:
                print(f"Cannot set offset. Offset has to be lower than {MAX_FRAGMENT_SIZE}.")
            else:
                fragment_size = size
                break
        except:
            print("Cannot set offset. Invalid value entered.")
    print(f"Offset set to {fragment_size}")


main()
