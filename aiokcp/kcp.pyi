"""
This type stub file was generated by cyright.
"""

from libc.stdint import *
from typing import Optional
from .exceptions import *

def get_current_time_ms(): # -> int:
    ...

class Clock:
    def get_time(self) -> int:
        ...
    


class KCP:
    def __init__(self, conv_id: int, max_transmission: int = ..., no_delay: bool = ..., update_interval: int = ..., resend_count: int = ..., no_congestion_control: bool = ..., send_window_size: int = ..., receive_window_size: int = ..., stream: int = ...) -> None:
        ...
    
    def set_stream(self, stream): # -> None:
        ...
    
    def get_conv_id(self): # -> unsigned int:
        ...
    
    def set_output_handler(self, handler): # -> None:
        ...
    
    def enqueue(self, data: bytes): # -> int:
        ...
    
    def receive(self, data: bytes): # -> None:
        ...
    
    def get_received(self) -> bytearray:
        ...
    
    def update(self, ts_ms: Optional[int] = ...): # -> None:
        ...
    
    def update_check(self, ts_ms: Optional[int] = ...) -> int:
        ...
    
    def flush(self): # -> None:
        ...
    
    def set_mtu(self, max_transmission: int): # -> None:
        ...
    
    def set_nodelay(self, no_delay: bool, update_interval: int, resend_count: int, no_congestion_control: bool): # -> None:
        ...
    
    def get_waitsnd(self) -> int:
        ...
    
    def get_peeksize(self) -> int:
        ...
    
    def update_loop(self): # -> None:
        ...
    
    def set_wndsize(self, send: int, receive: int): # -> None:
        ...
    
    @property
    def packet_available(self): # -> bool:
        ...
    
    def get_all_received(self): # -> Generator[bytearray, None, None]:
        ...
    
    def close(self): # -> None:
        ...
    

