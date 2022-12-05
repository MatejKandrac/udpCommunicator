from client_commons import *


class Sender(ClientCommons):

    fragment_size = 1468
    file_path: str
    connection_retries = 5
    WINDOW_SIZE = 5
    free_window = WINDOW_SIZE
    connecting = False
    preparing_transfer = False
    repeat_indexes = []
    fragments = []
    window_index = 0

    def __init__(self):
        super().__init__()

    def dispatch_message(self, host, msg_type, fragment, data):
        if msg_type == TYPE_ACTION_ACK:
            self.ack_lock = False
            if self.connecting:
                self.isConnected = True
                self.connecting = False
        if msg_type == TYPE_ALIVE_MESSAGE:
            self.lastAlive = time.time()
        if msg_type == TYPE_FRAGMENT_ACK:
            self.free_window += 1
            self.fragments[fragment]["ack_state"] = True
            print(f"ACK {fragment}")

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
            if now - self.fragments[i]["sent_time"] > 5:
                self.repeat_indexes.append(i)

    def send_bytes(self, data, start_payload):
        if len(data) > 2_097_152:
            print("Data payload is too large")
            return
        index = 0
        self.fragments = []
        for i in range(0, len(data), self.fragment_size):
            self.fragments.append({
                "index": index,
                "data": data[i: i + self.fragment_size],
                "sent_time": 0,
                "ack_state": False
            })
            index += 1
        self.window_index = 0
        self.ack_lock = True
        self.conn.sendto(self.build_packet(TYPE_PREPARE_TRANSMISSION, data=start_payload.encode()), self.client)
        while self.ack_lock:
            pass
        print("STARTING TRANSFER")
        while not self.all_data_sent():
            if self.free_window > 0:
                self.free_window -= 1
                fragment = self.get_preferred_fragment()
                if fragment is not None:
                    print(f"SENDING {fragment['index']}")
                    self.conn.sendto(self.build_packet(TYPE_DATA_FRAGMENT, fragment["index"], fragment["data"]), self.client)
                    fragment["sent_time"] = time.time()
            else:
                self.check_timeouts()
        self.ack_lock = True
        print("TRANSMISSION COMPLETED")
        self.conn.sendto(self.build_packet(TYPE_DATA_TRANSMISSION_COMPLETE), self.client)
        while self.ack_lock:
            pass

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
            self.send_bytes(data, "F"+split[len(split) - 1])
        except FileNotFoundError:
            print("File not found")
        except Exception:
            print("Error reading file")

    def loop(self):
        print("Ip addr: ", end='')
        ip_addr = input()
        print("Port: ", end='')
        port = int(input())
        if not self.connect(ip_addr, port):
            return
        try:
            while True:
                print("Type END to end")
                print("Type SWAP to swap roles")
                print("Type TXT to send text messages")
                print("Type FILE to send file")
                print("Type OFFSET to set fragment size")
                data = input()
                if data == "END":
                    self.soft_terminate()
                    break
                if data == "TXT":
                    self.text_transfer()
                if data == "FILE":
                    self.file_transfer()
                if data == "OFFSET":
                    self.change_offset()
        except Exception as e:
            print(f"ERROR {e}")
        self.hard_terminate()

    def connect(self, ip, conn_port):
        print("Connecting...")
        threading.Thread(target=self.data_handler).start()
        self.client = (ip, conn_port)
        retries = self.connection_retries
        self.connecting = True
        while not self.isConnected:
            self.conn.sendto(self.build_packet(TYPE_START_CONN), self.client)
            if retries == 0:
                print("Failed to connect")
                self.hard_terminate()
                return False
            time.sleep(1)
            retries -= 1
        print("Connected")
        self.start_keep_alive()
        return True

    def set_file_path(self, path):
        self.file_path = path

    def change_offset(self):
        print("Type int value of offset")
        self.fragment_size = int(input())
        print(f"Offset set to {self.fragment_size}")


sender = Sender()
sender.loop()
