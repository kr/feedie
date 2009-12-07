import sys
from collections import defaultdict
from twisted.internet.defer import Deferred

def merge(a, b):
  a = a.copy()
  a.update(b)
  return a

def mix_one(f, a, b):
  ap = (1 - f) * 1000
  bp = f * 1000
  return (a * ap + b * bp) / (ap + bp)

def mix(f, a, b):
  f = (f,) * len(a)
  return tuple((mix_one(*fab) for fab in zip(f, a, b)))

def leading(line_height, item_height):
  return line_height - item_height

def normalize_datetime(dt):
  xxx

class EventEmitter(Deferred):
  # The special event name "*" will register a listener for all events.
  def addListener(self, name, listener):
    assert callable(listener)
    self.init_listeners()
    self.listeners[name].append(listener)
    return self

  def chainEvents(self, other):
    self.addListener('*', other.emit)

  def emit(self, name, *args, **kw):
    self.init_listeners()
    for listener in self.listeners[name] + self.listeners['*']:
      try:
        listener(name, *args, **kw)
      except Exception, e:
        print >>sys.stderr, e

  def init_listeners(self):
    self.listeners = getattr(self, 'listeners', defaultdict(list))
