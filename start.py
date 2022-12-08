from client_commons import ClientCommons
from receiver import Receiver
from sender import Sender

client: ClientCommons
lastClient = ""

print("V 1")
print("Select mode:\nr - Receiver\ns - Sender")
data = input()
if data == "r":
    client = Receiver()
    lastClient = "r"
elif data == "s":
    client = Sender()
    lastClient = "s"
else:
    print("Invalid option, terminating.")
    exit(0)

while True:
    conn = client.loop()
    if conn:
        if client is Receiver:
            client = Sender(conn)
        else:
            client = Receiver(conn)
    else:
        break
