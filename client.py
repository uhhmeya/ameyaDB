import random
import socket
import struct
import threading
import time

NODE_HOSTNAMES = [
    f"node-{i}.ameyadb.internal" for i in range(5)]
CLIENT_PORT = 7000

OP_WR = 1
I_AM_LEADER, I_AM_NOT_LEADER, IDK = 1, 2, 3

stop_flag = threading.Event()
client_threads = []


def recv_exact(node, num_bytes):
    buf = b""
    while len(buf) < num_bytes:
        chunk = node.recv(num_bytes - len(buf))
        if not chunk:
            raise ConnectionError("node closed the connection mid-reply")
        buf += chunk
    return buf

def build_write(key, val):
    key_bytes, val_bytes = key.encode(), val.encode()
    return (bytes([OP_WR])
            + struct.pack("<I", len(key_bytes)) + key_bytes
            + struct.pack("<I", len(val_bytes)) + val_bytes)

def run_client(client_id):

    node = None
    guess = random.randrange(len(NODE_HOSTNAMES)) # guess leader!
    write_number = 0

    while not stop_flag.is_set():
        try:

            # if we are not connected to a node, then guess a leader!
            if node is None:
                node = socket.create_connection((NODE_HOSTNAMES[guess], CLIENT_PORT), timeout=2)
                node.settimeout(5)

            # send write to leader!
            key = f"c{client_id}-k{write_number}"
            val = f"v{write_number}"
            node.sendall(build_write(key, val))
            is_leader, leader = struct.unpack("<Bi", recv_exact(node, 5))

            if is_leader == I_AM_LEADER:
                write_number += 1

            # find leader!
            elif is_leader == I_AM_NOT_LEADER:
                node.close()
                node = None
                guess = leader

            elif is_leader == IDK:
                node.close()
                node = None
                guess = random.randrange(len(NODE_HOSTNAMES))

        # node down
        except OSError:
            if node:
                node.close()
            node = None
            guess = random.randrange(len(NODE_HOSTNAMES))
            time.sleep(0.05)

    # called after stop clients()
    if node:
        node.close()


def start_clients(num_clients):
    for client_id in range(num_clients):
        thread = threading.Thread(target=run_client, args=(client_id,), daemon=True)
        thread.start()
        client_threads.append(thread)


def stop_clients():
    stop_flag.set()
    for thread in client_threads:
        thread.join(timeout=5)