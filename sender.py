from client_commons import *


class Sender(ClientCommons):
    fragment_size = MAX_FRAGMENT_SIZE
    file_path: str
    free_window = WINDOW_SIZE
    canceling = False
    connecting = False
    preparing_transfer = False
    repeat_indexes = []
    fragments = []
    window_index = 0

    def __init__(self, conn=None):
        super().__init__()
        if conn:
            if not self.connect(conn=conn):
                print("Failed to connect, please reenter data")
        if not self.isConnected:
            while True:
                print("Ip addr: ", end='')
                ip_addr = input()
                print("Port: ", end='')
                port = int(input())
                if not self.connect(ip_addr, port):
                    print("Failed to connect, type n to terminate")
                    data = input()
                    if data == 'n':
                        self.canceling = True
                        break
                else:
                    self.init_success = True
                    break

    def dispatch_message(self, host, msg_type, fragment, data):
        if msg_type == TYPE_ACTION_ACK:
            self.ack_lock = False
            if self.connecting:
                self.isConnected = True
                self.connecting = False
        if msg_type == TYPE_ALIVE_MESSAGE:
            self.lastAlive = time.time()
        if msg_type == TYPE_TERMINATE_CONN:
            self.conn.sendto(self.build_packet(TYPE_ACTION_ACK), self.client)
            self.hard_terminate()
        if msg_type == TYPE_FRAGMENT_ACK:
            self.free_window += 1
            self.fragments[fragment]["ack_state"] = True
            print(f"ACKED {fragment}")
        if msg_type == TYPE_FRAGMENT_REPEAT:
            self.repeat_indexes.append(fragment)
            self.free_window += 1
            print(f"REPEAT REQUESTED {fragment}")

    def get_preferred_fragment(self):
        result: []
        if len(self.repeat_indexes) > 0:
            index = self.repeat_indexes[0]
            result = self.fragments[index]
            self.repeat_indexes.remove(index)
        else:
            if self.window_index == len(self.fragments):
                result = None
            else:
                result = self.fragments[self.window_index]
                self.window_index += 1
        return result

    def all_data_sent(self):
        if not ((self.window_index == len(self.fragments)) and len(self.repeat_indexes) == 0):
            return False
        for fragment in self.fragments:
            if not fragment["ack_state"]:
                return False
        return True

    def check_timeouts(self):
        now = time.time()
        for i in range(0, self.window_index):
            if (not self.fragments[i]["ack_state"]) and (now - self.fragments[i]["sent_time"] > 5):
                self.fragments[i]["sent_time"] = now
                self.free_window += 1
                self.repeat_indexes.append(i)

    def send_bytes(self, data, start_payload):
        if len(data) > 2_097_152:
            print("Data payload is too large")
            return
        print("Do you want to simulate errors? y/N")
        str_input = input()
        errors = False
        if (str_input == 'Y') or (str_input == 'y'):
            errors = True

        index = 0
        self.fragments = []
        for i in range(0, len(data), self.fragment_size):
            self.fragments.append({
                "index": index,
                "data": data[i: i + self.fragment_size],
                "sent_time": 0.0,
                "ack_state": False,
                "simulate_error": False if (not errors) else bool(random.getrandbits(1))
            })
            index += 1
        self.window_index = 0
        self.ack_lock = True
        self.free_window = WINDOW_SIZE
        self.conn.sendto(self.build_packet(TYPE_PREPARE_TRANSMISSION, fragment=index, data=start_payload.encode()), self.client)
        while self.ack_lock:
            pass
        print("STARTING TRANSFER")
        while not self.all_data_sent():
            if self.free_window > 0:
                self.free_window -= 1
                fragment = self.get_preferred_fragment()
                if fragment is not None:
                    print(f"SENDING {fragment['index']} corrupted: {fragment['simulate_error']}")
                    self.conn.sendto(self.build_packet(TYPE_DATA_FRAGMENT, fragment["index"], fragment["data"], fragment["simulate_error"]),
                                     self.client)
                    fragment["simulate_error"] = False
                    fragment["sent_time"] = time.time()
            else:
                self.check_timeouts()
        if not self.await_response(self.build_packet(TYPE_DATA_TRANSMISSION_COMPLETE)):
            print("Could not finish transmission. Aborting")
        else:
            print("TRANSMISSION COMPLETED")

    def text_transfer(self):
        print("Press ENTER to exit text transfer, otherwise type message to send")
        while True:
            text = input()
            if text == '':
                break
            self.send_bytes(text.encode(), "T")

    def file_transfer(self):
        print("Enter file path to send")
        path = input()
        try:
            file = open(path, "rb")
            delim = '/' if path.__contains__('/') else '\\'
            split = file.name.split(delim)
            data = file.read()
            file.close()
            self.send_bytes(data, "F" + split[len(split) - 1])
        except FileNotFoundError:
            print("File not found")
        except Exception:
            print("Error reading file")

    def loop(self):
        try:
            while self.isConnected:
                print("Type END to end")
                print("Type SWAP to swap roles")
                print("Type TXT to send text messages")
                print("Type FILE to send file")
                print("Type OFFSET to set fragment size")
                data = input()
                if data == "END":
                    self.soft_terminate()
                if data == "TXT":
                    self.text_transfer()
                if data == "FILE":
                    self.file_transfer()
                if data == "SWAP":

                    return self.client
                if data == "OFFSET":
                    self.change_offset()
        except Exception:
            self.hard_terminate()

    def connect(self, ip=None, conn_port=None, conn=None):
        print("Connecting...")
        threading.Thread(target=self.data_handler).start()
        self.client = conn if conn else (ip, conn_port)
        self.connecting = True
        if not self.await_response(self.build_packet(TYPE_START_CONN)):
            print("Failed to connect")
            self.client = None
            return False
        print("Connected")
        self.start_keep_alive()
        return True

    def change_offset(self):
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
                    self.fragment_size = size
                    break
            except:
                print("Cannot set offset. Invalid value entered.")
        print(f"Offset set to {self.fragment_size}")
