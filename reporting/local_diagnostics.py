"""Offline probes. Read-only; unavailable external evidence stays UNKNOWN."""
import os
import platform
import socket
from .health import Health

def local_health(root):
    # Interface existence alone does not prove connectivity; do not return True.
    def interfaces():return {'state':'UNKNOWN','interfaces':[name for _,name in socket.if_nameindex()],'reason':'Interface inventory is not operational connectivity evidence'}
    def disk():
        stat=os.statvfs(root)
        return stat.f_bavail>0 and os.access(root,os.W_OK)
    return Health({'local.machine':lambda:bool(platform.system()),'network.interface':interfaces,'local.disk':disk})
