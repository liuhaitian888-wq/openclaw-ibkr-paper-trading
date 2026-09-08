"""Reusable deterministic sandbox failures. No credentials or network imports."""
import socket
import ssl
from .delivery import Rejected

class ProcessCrash(BaseException):pass

class Faults:
    def __init__(self,points=None):self.points=points or {};self.calls=[]
    def __call__(self,stage):
        self.calls.append(stage)
        fault=self.points.get(stage)
        if fault:
            if callable(fault):return fault()
            raise fault

class SandboxTransport:
    sandbox=True
    def __init__(self,upload_fault=None,send_fault=None,response=None,send_log=None):
        self.upload_fault=upload_fault;self.send_fault=send_fault;self.response=response or {'code':0};self.uploads=0;self.sends=0;self.send_log=send_log
    def upload(self,path):
        self.uploads+=1
        if self.upload_fault:raise self.upload_fault
        return 'img_sandbox_only'
    def send(self,key):
        self.sends+=1
        if self.send_log:
            with self.send_log.open('a') as stream:stream.write('sandbox send\n')
        if self.send_fault:raise self.send_fault
        return self.response

FAILURES={
 'no_network':('network.interface',False),
 'dns':('network.dns',socket.gaierror(-2,'synthetic DNS failure')),
 'route':('network.route',OSError(51,'synthetic network unreachable')),
 'endpoint':('feishu.endpoint',ConnectionRefusedError('synthetic endpoint refusal')),
 'tls':('network.tls',ssl.SSLError('synthetic TLS verification failure')),
 'auth':('feishu.auth',False),
 'disk':('local.disk',False),
 'ledger':('local.ledger',False),
}
