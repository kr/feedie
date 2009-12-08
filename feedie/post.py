from feedie.attrdict import attrdict

class Post(attrdict):

  @attrdict.default
  def b(self):
    return 2

  c = attrdict.constdefault('c', 3)
