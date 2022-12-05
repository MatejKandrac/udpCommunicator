from client_commons import *
from os import path


class Receiver(ClientCommons):

    isText = False
    fragmented_data = []
    current_index = 0
    save_path = ""

    def __init__(self, port=0):
        super().__init__()
        ip = socket.gethostbyname(socket.gethostname())
        self.conn.bind((ip, port))
        print(f"Server active, ip: {self.conn.getsockname()[0]} {self.conn.getsockname()[1]}")

    def loop(self):
        print("Type END to end")
        self.data_handler()
        self.hard_terminate()

    def accept_connection(self, host):
        self.conn.sendto(self.build_packet(TYPE_ACTION_ACK), host)
        self.client = host
        self.isConnected = True
        self.start_keep_alive()

    def build_data(self, fragment, data: bytes):
        print(f"BUILDING FRAGMENT {fragment}")
        self.conn.sendto(self.build_packet(TYPE_FRAGMENT_ACK, fragment), self.client)
        if fragment == self.current_index:
            self.current_index += 1
            self.fragmented_data.append(data)
        else:
            if fragment > self.current_index:
                for i in range(self.current_index, fragment):
                    self.fragmented_data.append(None)
                self.fragmented_data.append(fragment)
            else:
                self.fragmented_data[fragment] = data

    def prepare_transmission(self, data: bytes):
        print(f"PREPARING TRANSFER {data}")
        parsed_data = data.decode()
        self.isText = parsed_data[0] == 'T'
        self.fragmented_data = []
        self.current_index = 0
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
            print(self.fragmented_data)
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
            self.accept_connection(host)
        if msg_type == TYPE_TERMINATE_CONN:
            self.isConnected = False
        if msg_type == TYPE_PREPARE_TRANSMISSION:
            threading.Thread(target=self.prepare_transmission, args=(data, )).start()
        if msg_type == TYPE_DATA_FRAGMENT:
            self.build_data(fragment, data)
        if msg_type == TYPE_DATA_TRANSMISSION_COMPLETE:
            self.finish_transfer()


receiver = Receiver()
receiver.loop()
