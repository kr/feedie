from collections import namedtuple
from twisted.internet import protocol, reactor, error
from twisted.web import http

from feedie import util

Status = namedtuple('Status', 'http_version code message')
Response = namedtuple('Response', 'status headers body')
Request = namedtuple('Request', 'method path headers body')

class HTTPProtocol(http.HTTPClient):
  def __init__(self, request, promise):
    self.request = request
    self.promise = promise
    self.content_length, self.content_progress = 0, 0
    self.headers = {}
    self.chunks = []

  def connectionMade(self):
    self.promise.emit('connected')
    self.sendCommand(self.request.method, self.request.path)
    for k, v in self.request.headers.items():
      self.sendHeader(k, v)
    #if self.request.body is not None:
    #  self.sendBody(body)
    self.endHeaders()
    self.promise.emit('sent')

  def handleStatus(self, version, code, message):
    self.status = Status(version, code, message)
    self.promise.emit('status', self.status)

  def handleHeader(self, key, value):
    key = key.lower()
    self.headers[key] = value
    if key == 'content-length':
      self.content_length = int(value)
    self.promise.emit('header', key, value)

  def handleEndHeaders(self):
    self.promise.emit('headers', self.headers)

  def handleResponsePart(self, chunk):
    self.chunks.append(chunk)
    self.content_progress += len(chunk)
    self.promise.emit('body', self.content_progress, self.content_length)

  def handleResponseEnd(self):
    self.complete()

  def connectionLost(self, reason):
    if reason.check(error.ConnectionDone):
      self.complete()
    if hasattr(self, 'promise'):
      self.promise.errback(reason)
      del self.promise

  def complete(self):
    if hasattr(self, 'promise'):
      body = ''.join(self.chunks)
      resp = Response(self.status, self.headers, body)
      self.promise.callback(resp)
      del self.promise

class Client:
  def __init__(self, host, port):
    self.host = host
    self.port = port

  def request(self, method, path, headers=None, body=None):
    if headers is None: headers = {}

    path = path or '/'

    promise = util.EventEmitter()
    headers = util.merge(self.default_headers, headers)
    request = Request(method, path, headers, body)
    clientCreator = protocol.ClientCreator(reactor, HTTPProtocol, request,
        promise)
    d = clientCreator.connectTCP(self.host, self.port, timeout=30)
    d.addErrback(promise.errback)
    return promise

  @property
  def default_headers(self):
    return {
      'Host': self.host,
      'User-Agent': 'Feedie',
      'Connection': 'close',
    }

  def get(self, *args, **kw):
    return self.request('GET', *args, **kw)

  def head(self, *args, **kw):
    return self.request('HEAD', *args, **kw)

  def post(self, *args, **kw):
    return self.request('POST', *args, **kw)

  def delete(self, *args, **kw):
    return self.request('DELETE', *args, **kw)

  def put(self, *args, **kw):
    return self.request('PUT', *args, **kw)

