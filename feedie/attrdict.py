
class attrdict(dict):
  def __getattr__(self, name):
    return self[name]

  def __setattr__(self, name, value):
    self[name] = value

  @staticmethod
  def default(method):
    def getter(self):
      if method.__name__ in self:
        return self[method.__name__]
      return method(self)
    getter.__name__ = method.__name__
    return property(getter)

  @staticmethod
  def constdefault(name, value):
    def getter(self):
      return self.get(name, value)
    getter.__name__ = name
    return property(getter)

if __name__ == '__main__':
  class X(attrdict):
    b = attrdict.constdefault('b', 2)

    @attrdict.default
    def c(self):
      return 3

  x = X(a=1)
  print x.a
  print x.b
  print x.c
  x.b = 5
  x.c = 7
  print x.b
  print x.c
