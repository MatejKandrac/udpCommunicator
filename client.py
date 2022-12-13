# Author: Matej Kandráč

import socket
import threading
import multiprocessing
import subprocess
import ctypes
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

WINDOW_SIZE = 10
RETRY_COUNT = 5
TIMEOUT = 2
MAX_FRAGMENT_SIZE = 1467
KEEP_ALIVE_TIMEOUT = 25
KEEP_ALIVE_SEND_PERIODIC = 5
SENDING_FRAGMENT_TIMEOUT = 5
MAX_DATA_PAYLOAD = 2_097_152

INIT_TYPE_FILE = "F"
INIT_TYPE_TEXT = "T"
INIT_TYPE_FILENAME = "N"

# DEFINE HELPER VARIABLES
is_connected = False
ack_lock = False
swapping = False
last_alive = 0
client = None
is_sender = False
transfer_type = ""
terminating = False
keyboard_interrupt = False
transmission_in_progress = False
file_path = ""
fragment_size = MAX_FRAGMENT_SIZE
free_window = WINDOW_SIZE
repeat_indexes = []
fragmented_data = []
window_index = 0

# DEFINE SOCKET
conn = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
conn.settimeout(1)


# Main function initializes first mode of client and launches loop function
def main():
    global is_sender, terminating
    print("Select mode:\nr - Receiver\ns - Sender")
    data = input()
    if (data == "r") or data == "s":
        threading.Thread(target=data_handler).start()
        time.sleep(0.1)
        if data == "r":
            is_sender = False
            if not init_receiver():
                terminating = True
                return
        elif data == "s":
            is_sender = True
            if not init_sender():
                terminating = True
                return
    else:
        print("Invalid option, terminating.")
        exit(0)
    loop()


# Method waits for user input. It runs on different process so it can be terminated easily
def input_process(str_input,):
    std_in = open(0)
    data = std_in.readline()
    str_input.value = data[0: len(data) - 1]


# Method starts input process and waits for input. Terminates if keyboard_interrupt flag is true and returns None
def interruptable_input():
    global keyboard_interrupt
    manager = multiprocessing.Manager()
    str_input = manager.Value(ctypes.c_char_p, None)
    process = multiprocessing.Process(target=input_process, args=(str_input,))
    process.start()
    while (not keyboard_interrupt) and (str_input.value is None):
        pass
    process.terminate()
    process.join()
    if keyboard_interrupt:
        print("Input terminated by other process")
        keyboard_interrupt = False
        return None
    return str_input.value


# Loop method prints user actions on screen and executes methods. Actions vary depending on mode
def loop():
    global is_connected, is_sender, swapping
    try:
        while True:
            if is_sender:
                print("Type END to end")
                print("Type SWAP to swap roles")
                print("Type TXT to send text messages")
                print("Type FILE to send file")
                print("Type OFFSET to set fragment size")
                data = interruptable_input()
                if data is None:
                    pass
                elif data == "END":
                    soft_terminate()
                    break
                elif data == "TXT":
                    text_transfer()
                elif data == "FILE":
                    file_transfer()
                elif data == "SWAP":
                    if await_response(build_packet(TYPE_SWAP_MODE)):
                        swapping = True
                    else:
                        print("Could not swap. Client did not respond")
                elif data == "OFFSET":
                    change_offset()
            elif not transmission_in_progress and is_connected:
                print("Type SWAP to swap roles")
                data = interruptable_input()
                if data is None:
                    pass
                elif data == 'SWAP':
                    if await_response(build_packet(TYPE_SWAP_MODE)):
                        swapping = True
                    else:
                        print("Could not swap. Client did not respond")
            else:
                time.sleep(0.1)
            if terminating:
                break
            if swapping:
                is_sender = not is_sender
                swapping = False
                print(f"SWAPPING TO MODE {'SENDER' if is_sender else 'RECEIVER'}")
        hard_terminate()
    except KeyboardInterrupt:
        exit(0)
    except Exception as e:
        print(e)
        hard_terminate()


# Method initializes receiver as first mode
def init_receiver():
    global conn
    try:
        data = subprocess.check_output(['hostname', '-I'])
        ip = data.decode().split(' ')[0]
    except:
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


# Method initializes sender as first client
def init_sender():
    global conn
    while True:
        print("Ip addr: ", end='')
        ip_addr = input()
        print("Port: ", end='')
        port = input()
        if not connect(ip_addr, port):
            print("Failed to connect, type n to terminate")
            data = input()
            if data == 'n':
                return False
        else:
            return True


# Function calculates CRC16 of given data
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
# Detects corruptions or data and starts dispatcher thread so it can listen again without block
def data_handler():
    print("Starting data handler job")
    while not terminating:
        try:
            pair = conn.recvfrom(1472)
            data = pair[0]
            msg_type = data[0] >> 4
            fragment = ((data[0] & 0x0F) << 16) + (data[1] << 8) + data[2]
            if not check_corrupted(data):
                print(f"Corrupted data detected {fragment}")
                dispatch_corrupted(msg_type, fragment)
            else:
                data = data[3: len(data) - 2]
                dispatch_message(pair[1], msg_type, fragment, data)
        except socket.timeout:
            pass
        except OSError:
            pass


# Function works as ack required send. Client sends the packet with retry count and waits for acknowledgement
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


# Function hard terminates the client, interrupting any input and closing connection
def hard_terminate():
    global is_connected
    global keyboard_interrupt
    global terminating
    global ack_lock
    terminating = True
    keyboard_interrupt = True
    ack_lock = False
    is_connected = False
    conn.close()


# Function soft terminates, waits for other user acknowledgement and terminates
def soft_terminate():
    if await_response(build_packet(TYPE_TERMINATE_CONN)):
        hard_terminate()
    else:
        print("Could not end connection due to client not responding.")


# Method periodically sends keep alive packets to other client.
# Also checks if other client responded in recent time, if not it hard terminates the client
def keep_alive():
    global last_alive
    last_alive = time.time()
    last_sent_millis = time.time()
    print("Starting keep alive job")
    while is_connected:
        if time.time() - last_sent_millis > KEEP_ALIVE_SEND_PERIODIC:
            try:
                conn.sendto(build_packet(TYPE_ALIVE_MESSAGE), client)
                last_sent_millis = time.time()
            except:
                pass
        if (time.time() - last_alive) > KEEP_ALIVE_TIMEOUT:
            print("Keep alive exceeded, terminating.")
            hard_terminate()
        time.sleep(0.1)
    print("Terminating keep alive job")


# Function checks if data is corrupted. It calculates the CRC from data and compares it to attached CRC
def check_corrupted(data):
    crc_data = data[len(data) - 2:]
    crc = (crc_data[0] << 8) + crc_data[1]
    return crc16(data[:len(data) - 2]) == crc


# Function accepts connection from other host, remembering it and setting state as connected
def accept_connection(host):
    print(f"HOST CONNECTED: {host}")
    global client
    global is_connected
    conn.sendto(build_packet(TYPE_ACTION_ACK), host)
    client = host
    is_connected = True
    threading.Thread(target=keep_alive).start()


# Funciton prepares a transmission, reads data and filename and asks user for save path
def prepare_transmission(fragments, data: bytes):
    global transfer_type
    global fragmented_data
    global file_path
    global keyboard_interrupt
    global transmission_in_progress
    parsed_data = data.decode()
    transfer_type = parsed_data[0]
    fragmented_data = [None] * fragments
    if transfer_type == INIT_TYPE_FILE:
        filename = file_path
        while True:
            transmission_in_progress = True
            keyboard_interrupt = True
            time.sleep(0.1)
            print(f"Enter path for receiving file {filename}")
            file_path = interruptable_input()
            if file_path is None:
                return
            if path.isdir(file_path) and path.exists(file_path):
                break
            print("Invalid path. Please reenter")
        if not file_path.endswith('/') or file_path.endswith('\\'):
            delim = '/' if file_path.count('/') else '\\'
            file_path += delim
        file_path += filename
    conn.sendto(build_packet(TYPE_ACTION_ACK), client)


# Function finishes the transfer, saving data to file or printing data depending if it is text or file
def finish_transfer():
    global file_path
    global transmission_in_progress
    conn.sendto(build_packet(TYPE_ACTION_ACK), client)
    if transfer_type == INIT_TYPE_TEXT:
        print("Got text message: ", end='')
        for fragment in fragmented_data:
            for char in fragment:
                print(chr(char), end='')
    elif transfer_type == INIT_TYPE_FILENAME:
        filename = ""
        for fragment in fragmented_data:
            for char in fragment:
                filename += chr(char)
        file_path = filename
    else:
        file = open(file_path, 'wb')
        for fragment in fragmented_data:
            file.write(fragment)
        file.close()
        print(f"Saved file to {file_path}")
    transmission_in_progress = False
    print()


# Function dispatches message. Every message type is for something else
def dispatch_message(host, msg_type, fragment, data):
    global last_alive
    global swapping
    global ack_lock
    global is_connected
    global free_window
    global keyboard_interrupt
    if msg_type == TYPE_ACTION_ACK:
        ack_lock = False
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
    if msg_type == TYPE_PREPARE_TRANSMISSION:
        threading.Thread(target=prepare_transmission, args=(fragment, data)).start()
    if msg_type == TYPE_DATA_FRAGMENT:
        print(f"RECEIVED FRAGMENT {fragment}")
        fragmented_data[fragment] = data
        conn.sendto(build_packet(TYPE_FRAGMENT_ACK, fragment), client)
    if msg_type == TYPE_DATA_TRANSMISSION_COMPLETE:
        finish_transfer()
    if msg_type == TYPE_SWAP_MODE:
        swapping = True
        keyboard_interrupt = True
        conn.sendto(build_packet(TYPE_ACTION_ACK), client)


# Function handles corrupted messages. If message is data fragment, data is allocated and fragment is not out of bounds,
# it requests fragment repetition
def dispatch_corrupted(msg_type, fragment):
    if not is_sender:
        if ((fragmented_data is not None) and (fragment < len(fragmented_data))) and (msg_type == TYPE_DATA_FRAGMENT):
            conn.sendto(build_packet(TYPE_FRAGMENT_REPEAT, fragment), client)


# Function gets preferred fragment to send. Prioritizes fragments to repeat and if there are none, then it uses next index
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


# Function checks if all of the fragments were sent and are acknowledged by other client
def all_data_sent():
    if not ((window_index == len(fragmented_data)) and len(repeat_indexes) == 0):
        return False
    start_index = 0 if window_index < WINDOW_SIZE else window_index - WINDOW_SIZE
    for i in range(start_index, window_index):
        if not fragmented_data[i]["ack_state"]:
            return False
    return True


# Function checks for fragments which are timed out. If there are some, we add them to repeat indexes for the next send
def check_timeouts():
    global free_window
    now = time.time()
    for i in range(0, window_index):
        if (not fragmented_data[i]["ack_state"]) and \
                (now - fragmented_data[i]["sent_time"] > SENDING_FRAGMENT_TIMEOUT):
            fragmented_data[i]["sent_time"] = now
            free_window += 1
            repeat_indexes.append(i)


def send_bytes(data, start_payload, ask_errors=True):
    global window_index
    global ack_lock
    global free_window
    global fragmented_data
    if len(data) > MAX_DATA_PAYLOAD:
        print("Data payload is too large")
        return
    errors = False
    if ask_errors:
        print("Do you want to simulate errors? y/N")
        str_input = interruptable_input()
        if str_input is None:
            return
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
        if terminating:
            return
        if free_window > 0:
            free_window -= 1
            fragment = get_preferred_fragment()
            if fragment is not None:
                print(f"SENDING {fragment['index']} corrupted: {fragment['simulate_error']}")
                try:
                    conn.sendto(build_packet(TYPE_DATA_FRAGMENT, fragment["index"],
                                             fragment["data"], fragment["simulate_error"]), client)
                    fragment["simulate_error"] = False
                    fragment["sent_time"] = time.time()
                except:
                    free_window += 1
                    window_index -= 1
        else:
            check_timeouts()
    if not await_response(build_packet(TYPE_DATA_TRANSMISSION_COMPLETE)):
        print("Could not finish transmission. Aborting")
    else:
        print("TRANSMISSION COMPLETED")


# Method loops forever, sending messages as bytes to other client
def text_transfer():
    print("Press ENTER to exit text transfer, otherwise type message to send")
    while True:
        text = interruptable_input()
        if text is None:
            return
        if text == '':
            break
        send_bytes(text.encode(), INIT_TYPE_TEXT)


# Method opens a file and sends the data to other client
def file_transfer():
    print("Enter file path to send")
    path = interruptable_input()
    try:
        file = open(path, "rb")
        delim = '/' if path.__contains__('/') else '\\'
        split = file.name.split(delim)
        data = file.read()
        file.close()
        send_bytes(split[len(split) - 1].encode(), INIT_TYPE_FILENAME, False)
        send_bytes(data, INIT_TYPE_FILE)
    except FileNotFoundError:
        print("File not found")
    except Exception as e:
        print(f"Error occurred {e}")


# Method connects to ip and port with retry count. Sets connected arguments
def connect(ip, conn_port):
    global client
    global is_connected
    print("Connecting...")
    try:
        client = (ip, int(conn_port))
        if not await_response(build_packet(TYPE_START_CONN)):
            print("Failed to connect")
            client = None
            return False
    except:
        print("Invalid data entered")
        return False
    print("Connected")
    is_connected = True
    threading.Thread(target=keep_alive).start()
    return True


# Method changes the offset which user types in
def change_offset():
    global fragment_size
    print("Type int value of offset")
    while True:
        size_str: str = interruptable_input()
        if size_str is None:
            return
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


if __name__ == '__main__':
    main()
