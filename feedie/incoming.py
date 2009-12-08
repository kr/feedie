import feedparser

class Feed:
  def __init__(self, xml):
    self.xml = xml
    self.parsed = feedparser.parse(xml)
    self.feed = self.parsed.feed

  def __getattr__(self, name):
    return getattr(self.feed, name)

  def __getitem__(self, name):
    return self.feed[name]

  @property
  def is_feed(self):
    return bool(self.parsed.version)

  @property
  def title(self):
    return self.get('title', '(unknown title)')

  @property
  def subtitle(self):
    return self.get('subtitle', '')

  @property
  def posts(self):
    for entry in self.parsed.entries:
      yield Post(entry)

class Post:
  def __init__(self, post):
    self.post = post

  def __getattr__(self, name):
    return getattr(self.post, name)

  def __getitem__(self, name):
    return self.post[name]

  @property
  def updated_at(self):
    return '123'

