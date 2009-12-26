import re
import urlparse
import httplib2
from collections import namedtuple
from twisted.internet import protocol, reactor, error, defer
from twisted.web import http

from feedie import util

Status = namedtuple('Status', 'http_version code message')
Response = namedtuple('Response', 'status headers body')
Request = namedtuple('Request', 'method path headers body')

class InvalidStateError(Exception):
  pass

class UnsupportedSchemeError(Exception):
  pass

class BadURIError(Exception):
  pass

class Protocol(http.HTTPClient):
  status = None
  _promise = None

  def __init__(self, host, port):
    self.state = 'new'
    self.host = host
    self.port = port
    self.close_notify = defer.Deferred()

  def connectionMade(self):
    if self.state == 'waiting-for-connection':
      self._proceed()
    else:
      assert self.state == 'new'
      self.state = 'idle'

  def request(self, request):
    promise = util.EventEmitter()
    if self.state == 'new':
      self.state = 'waiting-for-connection'
      self._request = request
      self._promise = promise
      return promise

    if self.state == 'idle':
      self._request = request
      self._promise = promise
      self._proceed()
      return promise

    promise.errback(InvalidStateError())
    return

  def _proceed(self):
    self.firstLine = 1 # tell the superclass that it's a new connection
    self.length = None # tell the superclass that it's a new connection
    self.content_length, self.content_progress = 0, 0
    self.headers = {}
    self.chunks = []
    self.status = None

    self.state = 'busy'
    self._promise.emit('connected')

    if self.host == 'tieguy.org':
      print id(self), '>', self._request.method, str(self._request.path)
    self.sendCommand(self._request.method, str(self._request.path))
    for k, v in self._request.headers.items():
      if self.host == 'tieguy.org':
        print id(self), '>', k, v
      self.sendHeader(str(k), str(v))
    self.endHeaders()
    if self._request.body is not None:
      if self.host == 'tieguy.org':
        print id(self), '>', 'BODY'
      self.transport.write(str(self._request.body))

    self._promise.emit('sent')

  def handleStatus(self, version, code, message):
    assert self.state == 'busy'
    if self.host == 'tieguy.org':
      print id(self), '<', version, code, message
    self.status = Status(version, int(code), message)
    self._promise.emit('status', self.status)

  def handleHeader(self, key, value):
    assert self.state == 'busy'
    key = key.lower()
    self.headers[key] = value
    if self.host == 'tieguy.org':
      print id(self), '<', key, value
    if key == 'content-length':
      self.content_length = int(value)
    self._promise.emit('header', key, value)

  def handleEndHeaders(self):
    assert self.state == 'busy'
    self._promise.emit('headers', self.headers)

  def handleResponsePart(self, chunk):
    assert self.state == 'busy'
    self.chunks.append(chunk)
    self.content_progress += len(chunk)
    if self.host == 'tieguy.org':
      print id(self), '<', len(chunk)
    self._promise.emit('body', self.content_progress, self.content_length)

  def handleResponseEnd(self):
    assert self.state == 'busy'
    self.complete()

  def connectionLost(self, reason):
    self.state == 'closed'
    self.close_notify.errback(reason)

    if reason.check(error.ConnectionDone) and self.status:
      self.complete()

    if self._promise:
      promise = self._promise
      del self._promise
      promise.errback(reason)

  def complete(self):
    if self.host == 'tieguy.org':
      print id(self), 'complete'
    if self._promise:
      body = ''.join(self.chunks)
      resp = Response(self.status, self.headers, body)
      promise = self._promise
      del self._promise
      self.state = 'idle'
      promise.callback(resp)



def normalize_uri(uri):
  if ':' in uri: return uri
  return 'http://' + uri

class Client(object):
  '''
    This interface is based somewhat on httplib2.
  '''

  def __init__(self,
      max_connections=50,
      max_connections_per_domain=6):
    self._pools = {}
    self._pending = []
    self.max_connections = max_connections
    self.max_connections_per_domain = max_connections_per_domain

  def request(self, uri, method='GET', body=None, headers=None):
    print 'request (%d)' % self.count_active_connections, uri
    promise = util.EventEmitter()

    split_uri = urlparse.urlsplit(uri)
    scheme, netloc, uri_path, query, fragment = split_uri
    host = split_uri.hostname
    port = split_uri.port or 80

    request_path = (uri_path or '/') + ('?' + query if query else '')

    if scheme != 'http':
      promise.errback(UnsupportedSchemeError(scheme))
      return promise

    if not host:
      promise.errback(BadURIError(uri))
      return promise

    #headers = httplib2._normalize_headers(headers or {})
    headers = (headers or {}).copy()
    headers.setdefault('host', host + ('' if port == 80 else ':%d' % port))
    headers.setdefault('user-agent', 'Feedie')
    headers.setdefault('connection', 'Keep-Alive')
    if body is not None:
      body = str(body)
      headers.setdefault('content-length', str(len(body)))

    d = self._get_connection((host, port))

    @d.addCallback
    def d(conn):
      assert conn.state in ('new', 'idle')
      d = conn.request(Request(method, request_path, headers, body))
      if conn.state != 'waiting-for-connection':
        promise.emit('connected')
      d.chainEvents(promise)

      @d.addBoth
      def d(x):
        try:
          self._free_connection(conn)
        except Exception, ex:
          pass
        return x

      d.chainDeferred(promise)

    d.addErrback(promise.errback) # can't happen
    d.chainEvents(promise)
    return promise

  def _get_connection(self, point):
    promise = util.EventEmitter()
    self._pending.append((point, promise))
    self._process_connections()
    return promise

  def _free_connection(self, conn):
    point = conn.host, conn.port
    pool = self._pool(point)
    pool.free_connection(conn)

  def _process_connections(self):
    while True:
      promise, conn = self._get_next()
      if promise is None: break
      if promise == 'retry': continue
      promise.callback(conn)

  @property
  def count_active_connections(self):
    return sum(map(lambda x: len(x.in_use) + len(x.making),
                   self._pools.values()))

  def _get_next(self):
    def make_conn_for_promise(pool, promise):
      promise.emit('connecting')
      d = pool.make_conn()
      @d.addCallback
      def d(conn):
        pool.in_use.append(conn)
        promise.callback(conn)
      #d.chainDeferred(promise)
      d.addErrback(promise.errback)

    if self.count_active_connections >= self.max_connections:
      return None, None

    for i, (point, promise) in enumerate(self._pending):
      pool = self._pool(point)
      if len(pool.in_use) >= self.max_connections_per_domain:
        continue

      if pool.available:
        conn = pool.available.pop()
        assert conn.state == 'idle'
        pool.in_use.append(conn)
        del self._pending[i]
        return promise, conn

      elif not pool.making:
        del self._pending[i]
        make_conn_for_promise(pool, promise)
        return 'retry', None

    return None, None

  def _pool(self, point):
    if point not in self._pools:
      self._pools[point] = Pool(self, point)
    return self._pools[point]

class Pool(object):
  def __init__(self, client, point):
    self.client = client
    self.host, self.port = point
    self.in_use = []
    self.available = []
    self.making = []
    self.creator = protocol.ClientCreator(reactor, Protocol, *point)

  def free_connection(self, conn):
    if conn in self.in_use:
      self.in_use.remove(conn)
      if conn not in self.available:
        self.available.append(conn)
    reactor.callLater(0, self.client._process_connections)

  def make_conn(self):
    promise = defer.Deferred()

    d = self.creator.connectTCP(self.host, self.port, timeout=30)
    self.making.append(d)

    @d.addCallback
    def d(conn):
      self.making.remove(d)
      close_notify = conn.close_notify

      @close_notify.addErrback
      def close_notify(reason):
        if conn in self.in_use:
          self.in_use.remove(conn)
        if conn in self.available:
          self.available.remove(conn)
        reactor.callLater(0, self.client._process_connections)

      assert conn.state == 'idle'
      #self.available.append(conn)
      promise.callback(conn)
      reactor.callLater(0, self.client._process_connections)

    @d.addErrback
    def d(reason):
      promise.errback(reason)
      if d in self.making: self.making.remove(d)
      reactor.callLater(0, self.client._process_connections)

    return promise
