import random
import socket
import ctypes as c
import threading as t
import struct
from queue import Queue

class UDPBasedProtocol:
    def __init__(self, *, local_addr, remote_addr, send_loss=0.0):
        self.udp_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.remote_addr = remote_addr
        self.udp_socket.bind(local_addr)
        self.send_loss = send_loss

    def sendto(self, data):
        if random.random() < self.send_loss:
            # simulate that packet was lost
            return len(data)

        return self.udp_socket.sendto(data, self.remote_addr)

    def recvfrom(self, n):
        msg, addr = self.udp_socket.recvfrom(n)
        return msg


class MyTCPProtocol(UDPBasedProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ack = 0
        self.seq = 0
        self.is_data_recieved = t.Event()
        self.max_packet_size = 7000
        self.data_offset = 2 * c.sizeof(c.c_uint32) + 2 * c.sizeof(c.c_bool)
        self.udp_socket.settimeout(1)

        self.packet_queue = Queue()
        self.reciever = t.Thread(target=self._reciever, daemon=True)
        self.reciever.start()
    
    def _send_ack(self, ack):
        payload = struct.pack("I I ? ?", ack, 0, True, False)
        self.sendto(payload)
    
    def _reciever(self):
        local_seq = 0
        local_ack = 0
        split_buffer = None
        while True:
            data = None
            while (data is None):
                data = self.recvfrom(self.data_offset)
            ack, seq, is_ack, is_split = struct.unpack("I I ? ?", data)
            if is_ack:
                if ack > local_ack:
                    local_ack = ack
                    self.is_data_recieved.set()
                continue
            if (local_seq >= ack):
                self._send_ack(ack)
                continue
            
            data = self.recvfrom(ack - seq + self.data_offset)
            local_seq += len(data) - self.data_offset
            if (is_split and local_seq == ack):
                if (split_buffer is None):
                   split_buffer = data[self.data_offset:]
                else:
                    split_buffer += data[self.data_offset:]
                self._send_ack(ack)
                continue
            elif (split_buffer is not None and local_seq == ack):
                split_buffer += data[self.data_offset:]
                self._send_ack(ack)
                self.packet_queue.put(split_buffer)
                split_buffer = None
                continue

            if (local_seq == ack):
                self.packet_queue.put(data[self.data_offset:])
                self._send_ack(ack)


    def send(self, data: bytes):
        if (len(data) >= self.max_packet_size):
            bytes_sent = 0
            pack_counter = 0
            while (bytes_sent != len(data)):
                byte_from = pack_counter * self.max_packet_size
                byte_to = (pack_counter + 1) * self.max_packet_size
                if byte_to > len(data):
                    byte_to = len(data)
                self.ack += byte_to - byte_from
                header = struct.pack("I I ? ?", self.ack, self.seq, False, True)
                if (byte_to == len(data)):
                    header = header = struct.pack("I I ? ?", self.ack, self.seq, False, False)
                payload = header + data[byte_from:byte_to]
                bytes_sent += self._send_package(payload) - self.data_offset
                pack_counter += 1
            return bytes_sent
        else:
            self.ack += len(data)
            header = struct.pack("I I ? ?", self.ack, self.seq, False, False)
            payload = header + data
            return self._send_package(payload) - self.data_offset

    def _send_package(self, package):
        while (not self.is_data_recieved.wait(0.00003)):
            self.sendto(package)
        self.is_data_recieved.clear()
        self.seq = self.ack
        return len(package)


    def recv(self, n: int):
        data = self.packet_queue.get()
        return data[:min(n, len(data))]

