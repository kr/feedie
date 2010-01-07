from twisted.internet import defer

inf = float('inf')

class Group(object):
  def __init__(self, name, limit):
    self._name = name
    self.limit = limit
    self._running = 0
    self._queue = []

  def run(self, f, *args, **kw):
    promise = defer.Deferred()

    def start():
      self._running += 1
      d = f(*args, **kw)

      @d.addBoth
      def d(x):
        try:
          self._running -= 1
          self._process()
        except Exception, ex:
          pass
        return x

      d.chainDeferred(promise)

    self._queue.append(start)
    self._process()

    return promise

  def _process(self):
    while self._queue and self._running < self.limit:
      start = self._queue.pop(0)
      start()

class Throttler(object):
  def __init__(self, *args, **kw):
    for k, v in dict(*args, **kw).items():
      getattr(self, k).limit = v

  def __getattr__(self, name):
    x = Group(name, inf)
    setattr(self, name, x)
    return getattr(self, name)

