import calendar
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

  def __contains__(self, name):
    return name in self.post

  @property
  def updated_int(self):
    return int(calendar.timegm(self.updated_parsed))

  @property
  def created_int(self):
    return int(calendar.timegm(self.created_parsed))

  @property
  def published_int(self):
    return int(calendar.timegm(self.published_parsed))

  @property
  def updated_at(self):
    if 'updated_parsed' in self: return self.updated_int
    if 'created_parsed' in self: return self.created_int
    if 'published_parsed' in self: return self.published_int
    return 0

  @property
  def has_useful_updated_at(self):
    return self.updated_at > 0

  # try real hard to get a useful id for this post
  @property
  def id(self):
    if 'id' in self: return self['id']
    if 'link' in self: return self.link
    return str(self.updated_at)
