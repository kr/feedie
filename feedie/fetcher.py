from collections import defaultdict
import urlparse
from twisted.internet import reactor
from feedie import util
from feedie import http

GLOBAL_LIMIT = 50
PER_DOMAIN_LIMIT = 6

pending = []
open_counts = defaultdict(int) # default value of int() == 0

# Schedules the given URI to be fetched as soon as reasonable. Respects
# per-host and global limits on the number of open connections.
def fetch(uri, headers=None):
  if headers is None: headers = {}
  promise = util.EventEmitter()
  if not (uri.startswith('http://') or uri.startswith('https://')):
    uri = 'http://' + uri
  uri = urlparse.urlsplit(uri, 'http')
  path = uri.path
  if uri.query: path += '?' + uri.query

  def go():
    def fin(result, *args, **kw):
      open_counts[uri.hostname] -= 1
      return result

    promise.emit('fetch')
    open_counts[uri.hostname] += 1
    d = http.Client(uri.hostname, uri.port or 80).get(path, headers=headers)
    d.addBoth(fin)
    d.chainDeferred(promise)
    d.chainEvents(promise)

  pending.append((uri.hostname, go))

  # Check if we can do some work, but not right now.
  reactor.callLater(0, iterate)

  return promise

# Do as much work as possible, but no more.
def iterate():
  while True:
    next = get_next()
    if not next: break
    next()

def get_next():
  if sum(open_counts.values()) < GLOBAL_LIMIT:
    for i in range(len(pending)):
      host, item = pending[i]
      if open_counts[host] < PER_DOMAIN_LIMIT:
        del pending[i]
        return item

