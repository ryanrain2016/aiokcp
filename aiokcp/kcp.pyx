#cython: language_level=3

from libc.stdint cimport *
from cpython.bytes cimport PyBytes_FromStringAndSize
from cpython cimport bool

import time
from typing import Optional

from .exceptions import *

cdef extern from "ikcp.h":
    # Structures
    struct IQUEUEHEAD:
        # Contents are unnecessary for our use case
        pass

    # KCP Control Object
    struct IKCPCB:
        uint32_t conv # Used to verify data is from the correct connection
        uint32_t mtu
        uint32_t mss
        uint32_t state
        uint32_t snd_una
        uint32_t snd_nxt
        uint32_t rcv_nxt
        uint32_t ts_recent
        uint32_t ts_lastack
        uint32_t ssthresh
        int32_t rx_rttval
        int32_t rx_srtt
        int32_t rx_rto
        int32_t rx_minrto
        uint32_t snd_wnd
        uint32_t rcv_wnd
        uint32_t rmt_wnd
        uint32_t cwnd
        uint32_t probe
        uint32_t current
        uint32_t interval
        uint32_t ts_flush
        uint32_t xmit
        uint32_t nrcv_buf
        uint32_t nsnd_buf
        uint32_t nrcv_que
        uint32_t nsnd_que
        uint32_t nodelay
        uint32_t updated
        uint32_t ts_probe
        uint32_t probe_wait
        uint32_t dead_link
        uint32_t incr
        IQUEUEHEAD snd_queue
        IQUEUEHEAD rcv_queue
        IQUEUEHEAD snd_buf
        IQUEUEHEAD rcv_buf
        uint32_t* acklist
        uint32_t ackcount
        uint32_t ackblock
        void* user # Just used to identify the connection it seems?
        char* buffer
        int32_t fastresend
        int32_t fastlimit
        int32_t nocwnd
        int32_t stream
        int32_t logmask
        int32_t (*output)(const char* buf, uint32_t len, IKCPCB* kcp, void *user)
        void (*writelog)(const char* log, IKCPCB* kcp, void* user);

    # Functions

    # Create KCP Control Object. User is passed to output callback.
    IKCPCB* ikcp_create(uint32_t conv, void* user)

    # Release KCP Control Object
    void ikcp_release(IKCPCB *kcp)

    # Sets the output callback function for KCP
    void ikcp_setoutput(IKCPCB *kcp, int32_t (*output)(const char* buf, uint32_t len, IKCPCB* kcp, void* user))

    # (User API) Handles received KCP data
    int32_t ikcp_recv(IKCPCB *kcp, char* buffer, int32_t len)

    # (User API) Send KCP data
    int32_t ikcp_send(IKCPCB *kcp, const char* buffer, int32_t len)

    # Update KCP timing.
    void ikcp_update(IKCPCB *kcp, uint32_t current)

    # Gives time till next ikcp_update() call in ms.
    uint32_t ikcp_check(IKCPCB *kcp, uint32_t current)

    # Low level UDP packet input, call it when you receive a low level UDP packet
    int32_t ikcp_input(IKCPCB *kcp, const char *data, long size)

    # Flush pending data
    void ikcp_flush(IKCPCB *kcp)

    # Checks the size of the next message in the recv queue
    int32_t ikcp_peeksize(IKCPCB *kcp)

    # Sets the MTU for KCP
    int32_t ikcp_setmtu(IKCPCB *kcp, int32_t mtu)

    # Checks how many packets are waiting to be sent
    int32_t ikcp_waitsnd(IKCPCB *kcp)

    # ?
    int32_t ikcp_nodelay(IKCPCB *kcp, int32_t nodelay, int32_t interval, int32_t resend, int32_t nc)

    void ikcp_wndsize(IKCPCB *kcp, int32_t sndwnd, int32_t rcvwnd)

#OutboundDataHandler = Callable[[KCP, bytes], None]

# Internally used in KCP whenever data is ready to be sent.
cdef int32_t handle_output_data(const char* buf, uint32_t len, IKCPCB* kcp, void* user) noexcept with gil:
    cdef KCP control = <KCP>user
    control.handle_output(buf, len)

cpdef get_current_time_ms():
    # Use perf counter as it isnt affected by system time changes.
    return time.perf_counter_ns() // 1000000

cdef class Clock:
    cdef uint64_t start_time
    cdef uint64_t last_time

    def __cinit__(self):
        self.start_time = get_current_time_ms()
        self.last_time = self.start_time

    cpdef uint32_t get_time(self):
        res = get_current_time_ms() - self.start_time
        self.last_time = res
        return <uint32_t>res


cdef class KCP:
    cdef IKCPCB* kcp
    # Correctly annotating this causes a cython compiler crash LOL
    cdef _data_handler # type: Optional[OutboundDataHandler]
    cdef Clock _clock
    cdef bool _is_closing
    cdef uint32_t conv_id

    def __init__(
        self,
        uint32_t conv_id,
        int max_transmission = 1400,
        bool no_delay = False,
        int update_interval = 100,
        int resend_count = 2,
        bool no_congestion_control = False,
        int send_window_size = 32,
        int receive_window_size = 128,
        int stream = 0,
    ):
        self.conv_id = conv_id
        self._data_handler = None
        # Create base KCP object, passing self as the user data to be passed to the callback.
        self.kcp = ikcp_create(
            conv_id,
            <void*>self,
        )

        ikcp_setoutput(self.kcp, handle_output_data)

        self.set_nodelay(
            no_delay,
            update_interval,
            resend_count,
            no_congestion_control
        )

        self.set_mtu(max_transmission)

        self.set_wndsize(send_window_size, receive_window_size)

        self.set_stream(stream)

        self._clock = Clock()

        self._is_closing = False

    def set_stream(self, stream):
        self.kcp.stream = int(stream)

    def get_conv_id(self):
        return self.conv_id

    cdef handle_output(self, const char* buf, int32_t len):
        # Create a bytes object from the buffer.
        cdef bytes data = PyBytes_FromStringAndSize(buf, len)
        self._data_handler(self, data)

    # Setting the handler for kcp output data.
    def set_output_handler(self, handler):
        self._data_handler = handler

    # I/O functions
    cpdef enqueue(self, bytes data):
        if self._data_handler is None:
            raise KCPException(
                "No output handler set. Cannot put output data to send. "
                "Try using the include_output_handler to set output handler."
            )

        cdef int32_t length = len(data)
        cdef char* buf = <char*>data
        cdef int32_t res = ikcp_send(self.kcp, buf, length)

        # Error handling
        if res < 0:
            raise KCPException(res)
        return res

    cpdef receive(self, bytes data):
        cdef int32_t length = len(data)
        cdef char* buf = <char*>data
        cdef int32_t res = ikcp_input(self.kcp, buf, length)
        # Error handling
        if res == -1:
            raise KCPConvMismatchError(
                "The conversation ID mismatch or invalid data."
            )
        elif res < -1:
            raise KCPException(res)

    # Gets the raw data received by KCP.
    cpdef bytearray get_received(self):
        # Check if there is any data to be received.
        cdef int length = ikcp_peeksize(self.kcp)
        if length == -1:
            return bytearray()

        # Create a buffer to store the data.
        cdef buf = bytearray(length)

        # Receive the data.
        cdef int32_t res = ikcp_recv(self.kcp, buf, length)
        if res < 0:
            raise KCPException(res)
        return buf


    cpdef update(self, ts_ms: Optional[int] = None):
        # Use python's time module if no timestamp is provided.
        if ts_ms is None:
            ts_ms = self._clock.get_time()

        ikcp_update(self.kcp, ts_ms)


    cpdef int update_check(self, ts_ms: Optional[int] = None):
        # Use python's time module if no timestamp is provided.
        if ts_ms is None:
            ts_ms = self._clock.get_time()
        cdef res = ikcp_check(self.kcp, ts_ms)
        return res

    cpdef flush(self):
        ikcp_flush(self.kcp)

    # Connection settings functions
    # Sets the size of the max packet size that can be sent.
    cpdef set_mtu(self, int max_transmission):
        ikcp_setmtu(self.kcp, max_transmission)

    # Sets nodelay options for KCP.
    cpdef set_nodelay(
        self,
        bool no_delay,
        int update_interval,
        int resend_count,
        bool no_congestion_control,
    ):
        ikcp_nodelay(
            self.kcp,
            <int32_t>no_delay,
            update_interval,
            resend_count,
            <int32_t>no_congestion_control
        )

    # Statistics functions
    # Returns the number of packets waiting to be sent.
    cpdef int32_t get_waitsnd(self):
        return ikcp_waitsnd(self.kcp)

    # Returns the size of the next packet to be received.
    cpdef int32_t get_peeksize(self):
        return ikcp_peeksize(self.kcp)

    cpdef update_loop(self):
        cdef int32_t next_update
        while not self._is_closing:
            next_update = self.update_check()
            time.sleep(next_update / 1000)
            self.update()

    cpdef set_wndsize(self, int send, int receive):
        ikcp_wndsize(self.kcp, send, receive)

    # Properties
    @property
    def packet_available(self):
        return self.get_peeksize() != -1

    # Generators
    def get_all_received(self):
        while ikcp_peeksize(self.kcp) != -1:
            yield self.get_received()

    def close(self):
        self._is_closing = True