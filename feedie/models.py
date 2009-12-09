import time
import couchdb
from desktopcouch.records.record import Record

from feedie import conn
from feedie import util
from feedie.attrdict import attrdict

class Model(object):
  def __model_init(self):
    try:
      self.__listeners
    except:
      self.__listeners = []

  def add_listener(self, x):
    self.__model_init()
    self.__listeners.append(x)

  def changed(self, arg=None):
    self.__model_init()
    for x in self.__listeners:
      x.update(self, arg)

class AllNewsSource(Model):
  def __init__(self):
    self.summary = Feed.get_summary()

  @property
  def id(self):
    return 'all-news'

  def post_summaries(self):
    rows = conn.database.db.view('feedie/feed_post',
        startkey=['feed', 0], endkey=['feed', 1])
    return [Post(row.value, self) for row in rows]

  @property
  def title(self):
    return 'All News'

  @property
  def icon(self):
    return None

  @property
  def category(self):
    return 'News'

  @property
  def unread(self):
    return self.total - self.read

  @property
  def total(self):
    return self.summary['total']

  @property
  def read(self):
    return self.summary['read']

class Sources(Model):
  def __init__(self):
    def feed_from_row(r):
      feed = Feed(r.value, summary.get(r.id, zero()), self)
      return r.id, feed

    self.builtins = {}
    rows = conn.database.db.view('feedie/feed')
    summary = {}
    for id, summ in Feed.get_summaries():
      summary[id] = summ

    zero = lambda:dict(total=0, read=0)
    self.feeds = dict(map(feed_from_row, rows))
    self.max_pos = max([0] + [x.pos for x in self.feeds.values()])

  def add_builtin(self, source):
    self.builtins[source.id] = source
    self.changed()

  def add_feed(self, feed):
    self.feeds[feed.id] = feed
    self.changed()
    return self.feeds[feed.id]

  def remove_feed(self, feed):
    if feed.id in self.feeds:
      raise RuntimeError('aaa')
      del self.feeds[feed.id]
      self.changed()

  def __iter__(self):
    feeds = sorted(self.feeds.values(), key=lambda x: (-x.pos, x.title, x.id))
    return iter(self.builtins.values() + feeds)

  def __getitem__(self, id):
    return self.builtins[id]

  def subscribe(self, uri, xml, ifeed):
    now = int(time.time())
    rec = None
    try:
      self.max_pos += 1
      doc = {}
      doc['type'] = 'feed'
      doc['title'] = ifeed.title
      doc['pos'] = self.max_pos
      doc['subtitle'] = ifeed.subtitle
      doc['subscribed_at'] = now
      conn.database.db[uri] = doc
    except couchdb.client.ResourceConflict:
      rec = conn.database.db[uri]
      rec['subscribed_at'] = now
      conn.database.db[uri] = rec
      rec = None
    rec = conn.database.db[uri]
    summary = Feed.get_summary(key=uri)
    feed = self.add_feed(Feed(rec, summary, self))
    for post in ifeed.posts:
      feed.save_post(post)
    return feed

  def update(self, feed, data=None):
    if feed.is_deleted:
      self.remove_feed(feed)

class Feed(Model):
  def __init__(self, doc, summary, sources):
    self.doc = doc
    self.summary = summary
    self.add_listener(sources)

  # Return a list of (uri, summary) pairs. Each summary is a small dictionary.
  @staticmethod
  def get_summaries(**kwargs):
    rows = conn.database.db.view('feedie/summary', group=True, **kwargs)
    return [(x.key, x.value) for x in rows]

  @staticmethod
  def get_summary(**kwargs):
    rows = conn.database.db.view('feedie/summary', **kwargs)
    for x in rows:
      return x.value
    return dict(total=0, read=0)

  def save_post(self, ipost, doc=None):
    if doc is None: doc = {}

    if not ipost.has_useful_updated_at: return

    post_id = '%s %s' % (self.id, ipost.id)

    print 'syncing', post_id

    doc['type'] = 'post'
    doc['title'] = ipost.get('title', '(unknown title)')
    doc['updated_at'] = ipost.updated_at
    doc['feed_id'] = self.id
    if 'link' in ipost: doc['link'] = ipost.link
    if 'summary' in ipost: doc['summary'] = ipost.summary
    if 'content' in ipost: doc['content'] = ipost.content # TODO use less-sanitized
    if 'published' in ipost: doc['published_at'] = ipost.published
    try:
      conn.database.db[post_id] = doc
      self.summary = Feed.get_summary(key=self.id)
      self.changed()
    except couchdb.client.ResourceConflict:
      return self.save_post(ipost, conn.database.db[post_id])

  @property
  def id(self):
    return self.doc['_id']

  def post_summaries(self):
    rows = conn.database.db.view('feedie/feed_post', key=['feed', 0, self.id])
    return [Post(row.value, self) for row in rows]

  @property
  def title(self):
    return self.doc.get('title', '(unknown title)')

  @property
  def icon(self):
    return 'cancel'

  @property
  def category(self):
    return 'News'

  @property
  def unread(self):
    return self.total - self.read

  @property
  def total(self):
    return self.summary['total']

  @property
  def read(self):
    return self.summary['read']

  @property
  def pos(self):
    return self.doc.get('pos', 0)

  @property
  def x_deleted_at(self):
    return self.doc.get('deleted_at', 0)

  @property
  def x_subscribed_at(self):
    return self.doc.get('subscribed_at', 0)

  @property
  def is_deleted(self):
    delat = self.x_deleted_at
    subat = self.x_subscribed_at
    return delat > subat

  def delete(self):
    self.doc['deleted_at'] = int(time.time())
    conn.database.db[self.id] = self.doc
    self.changed()

class Post(Model):
  __slots__ = 'doc source'.split()

  def __init__(self, doc, source):
    self.doc = attrdict(doc)
    self.source = source

  def __getitem__(self, name):
    return self.doc[name]

  def __setitem__(self, name, value):
    self.doc[name] = value

  def __contains__(self, name):
    return name in self.doc

  def __getattr__(self, name):
    return getattr(self.doc, name)

  def __setattr__(self, name, value):
    if name in self.__slots__:
      return Model.__setattr__(self, name, value)
    setattr(self.doc, name, value)
