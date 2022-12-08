from client_commons import *
from os import path


class Receiver(ClientCommons):

    isText = False
    fragmented_data = None
    save_path = ""

    def __init__(self, conn=None):
        super().__init__()
        if not conn:
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
                            self.conn.bind((ip, port))
                            break
                    except Exception:
                        print("Invalid number entered, try again")
                else:
                    self.conn.bind((ip, 0))
                    break
        else:
            self.conn.bind(conn)
        self.init_success = True
        print(f"Server active, ip: {self.conn.getsockname()[0]} {self.conn.getsockname()[1]}")

    def loop(self):
        try:
            self.data_handler()
        except Exception as e:
            print(e)
            self.hard_terminate()
        if self.swapping:
            return self.client

    def accept_connection(self, host):
        self.conn.sendto(self.build_packet(TYPE_ACTION_ACK), host)
        self.client = host
        self.isConnected = True
        self.start_keep_alive()

    def build_data(self, fragment, data: bytes):
        print(f"RECEIVED FRAGMENT {fragment}")
        self.fragmented_data[fragment] = data
        self.conn.sendto(self.build_packet(TYPE_FRAGMENT_ACK, fragment), self.client)

    def prepare_transmission(self, fragments, data: bytes):
        parsed_data = data.decode()
        self.isText = parsed_data[0] == 'T'
        self.fragmented_data = [None] * fragments
        if not self.isText:
            filename = parsed_data[1:]
            while True:
                print(f"Enter path for receiving file {filename}")
                self.save_path = input()
                if path.isdir(self.save_path) and path.exists(self.save_path):
                    break
                print("Invalid path. Please reenter")
            if not self.save_path.endswith('/') or self.save_path.endswith('\\'):
                delim = '/' if self.save_path.count('/') else '\\'
                self.save_path += delim
            self.save_path += filename
        self.conn.sendto(self.build_packet(TYPE_ACTION_ACK), self.client)

    def finish_transfer(self):
        print(f"FINISHING TRANSFER")
        self.conn.sendto(self.build_packet(TYPE_ACTION_ACK), self.client)
        if self.isText:
            print("Got text message: ", end='')
            for fragment in self.fragmented_data:
                for char in fragment:
                    print(chr(char), end='')
        else:
            file = open(self.save_path, 'wb')
            for fragment in self.fragmented_data:
                file.write(fragment)
            file.close()
            print(f"Saved file to {self.save_path}")
        print()

    def dispatch_message(self, host, msg_type, fragment, data):
        if msg_type == TYPE_ALIVE_MESSAGE:
            self.lastAlive = time.time()
        if msg_type == TYPE_START_CONN:
            if not self.client:
                self.accept_connection(host)
        if msg_type == TYPE_TERMINATE_CONN:
            self.conn.sendto(self.build_packet(TYPE_ACTION_ACK), self.client)
            self.hard_terminate()
        if msg_type == TYPE_PREPARE_TRANSMISSION:
            threading.Thread(target=self.prepare_transmission, args=(fragment, data, )).start()
        if msg_type == TYPE_DATA_FRAGMENT:
            self.build_data(fragment, data)
        if msg_type == TYPE_DATA_TRANSMISSION_COMPLETE:
            self.finish_transfer()
        if msg_type == TYPE_SWAP_MODE:
            self.swapping = True
            self.hard_terminate()

    def dispatch_corrupted(self, host, msg_type, fragment):
        print(f"{(self.fragmented_data is not None)} {fragment < len(self.fragmented_data)} {msg_type == TYPE_DATA_FRAGMENT}")
        if ((self.fragmented_data is not None) and (fragment < len(self.fragmented_data))) and (msg_type == TYPE_DATA_FRAGMENT):
            self.conn.sendto(self.build_packet(TYPE_FRAGMENT_REPEAT, fragment), self.client)
