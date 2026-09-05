import random
import socket
import struct
import threading
import time

NODES       = [f"node-{i}.ameyadb.internal" for i in range(5)]
CLIENT_PORT = 7000

WRITE = 1

# is node we are talking to a leader?
WR_OK, WR_NOT_LEADER = 1, 2


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("peer closed mid-response")
        buf += chunk
    return buf


class Stats:

    def __init__(self):
        self._lock     = threading.Lock()
        self.committed = 0
        self.failed    = 0
        self.redirects = 0
        self.conn_errs = 0
        self.by_leader = {}          # node id -> how many commits it served

    def commit(self, node_id):
        with self._lock:
            self.committed += 1
            self.by_leader[node_id] = self.by_leader.get(node_id, 0) + 1

    def bump(self, field):
        with self._lock:
            setattr(self, field, getattr(self, field) + 1)

    def snapshot(self):
        with self._lock:
            return {
                "committed": self.committed,
                "failed":    self.failed,
                "redirects": self.redirects,
                "conn_errs": self.conn_errs,
                "by_leader": dict(self.by_leader),
            }

class RaftClient:

    def __init__(self, client_id, stats, stop_event):
        self.client_id = client_id
        self.stats     = stats
        self.stop      = stop_event
        self.leader    = None        # cached leader id; None = pick at random
        self.sock      = None

    def _connect(self, node_id):
        self._close()
        self.sock = socket.create_connection((NODES[node_id], CLIENT_PORT), timeout=2)
        self.sock.settimeout(5)      # a partitioned leader must not hang us forever
        self.leader = node_id

    def _close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def write(self, key, value, max_tries=20):
        kb, vb = key.encode(), value.encode()
        frame = (bytes([WRITE])
                 + struct.pack("<I", len(kb)) + kb
                 + struct.pack("<I", len(vb)) + vb)

        for _ in range(max_tries):
            if self.stop.is_set():
                return False

            target = self.leader if self.leader is not None else random.randrange(len(NODES))

            try:
                if self.sock is None or target != self.leader:
                    self._connect(target)
                self.sock.sendall(frame)
                status, hint = struct.unpack("<Bi", _recv_exact(self.sock, 5))

            except (OSError, ConnectionError):
                # down, partitioned, or mid-restart -- forget it and ask elsewhere
                self._close()
                self.leader = None
                self.stats.bump("conn_errs")
                time.sleep(0.1)
                continue

            if status == WR_OK:
                self.stats.commit(hint)
                return True

            if status == WR_NOT_LEADER:
                self.stats.bump("redirects")
                self._close()
                self.leader = hint if 0 <= hint < len(NODES) else None
                if self.leader is None:
                    time.sleep(0.2)      # election in flight, don't spin hot
                continue

            self._close()                # unknown status = desync, start over
            self.leader = None

        self.stats.bump("failed")
        return False

class ClientPool:

    def __init__(self, num_clients=10, think_ms=(10, 50)):
        self.stats       = Stats()
        self.stop        = threading.Event()
        self.num_clients = num_clients
        self.think_ms    = think_ms
        self._threads    = []

    def _worker(self, cid):
        c   = RaftClient(cid, self.stats, self.stop)
        seq = 0
        lo, hi = self.think_ms
        while not self.stop.is_set():
            c.write(f"c{cid}-k{seq}", f"v{seq}")
            seq += 1
            time.sleep(random.uniform(lo, hi) / 1000.0)
        c._close()

    def start(self):
        self._threads = [
            threading.Thread(target=self._worker, args=(cid,), daemon=True)
            for cid in range(self.num_clients)
        ]
        for t in self._threads:
            t.start()

    def shutdown(self, timeout=5):
        self.stop.set()
        for t in self._threads:
            t.join(timeout=timeout)