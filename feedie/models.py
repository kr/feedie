import time
import couchdb
from collections import defaultdict
from desktopcouch.records.record import Record
from twisted.internet import reactor

from feedie import conn
from feedie import util
from feedie.attrdict import attrdict

class Model(object):
  def __model_init(self):
    self.handlers = getattr(self, 'handlers', defaultdict(list))

  def connect(self, name, handler):
    assert callable(handler)
    self.__model_init()
    self.handlers[name].append(handler)
    return self

  def emit(self, name, *args, **kwargs):
    self.__model_init()
    for handler in self.handlers[name] + self.handlers['*']:
      reactor.callLater(0, handler, self, name, *args, **kwargs)

class AllNewsSource(Model):
  def __init__(self):
    self.sources = None
    self.update_summary()

  def added_to(self, sources):
    self.sources = sources
    sources.connect('feed-added', self.feed_added)
    sources.connect('feed-removed', self.feed_removed)
    for feed in sources.feeds.values():
      feed.connect('summary-changed', self.summary_changed)
    self.update_summary()

  def feed_added(self, sources, event, feed):
    feed.connect('summary-changed', self.summary_changed)
    self.update_summary()

  def feed_removed(self, sources, event, feed):
    self.update_summary()

  def summary_changed(self, source, event):
    self.update_summary()

  def update_summary(self):
    self.summary = attrdict(total=0, read=0)
    if self.sources:
      for feed in self.sources:
        self.summary.total += feed.summary['total']
        self.summary.read += feed.summary['read']
    self.emit('summary-changed')

  @property
  def id(self):
    return 'all-news'

  def post_summaries(self):
    print 'keys', self.sources.feed_ids
    rows = conn.database.db.view('feedie/feed_post',
        keys=self.sources.feed_ids)
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
      feed = Feed(r.value, summary.get(r.id, zero()))
      feed.connect('deleted', self.feed_deleted)
      return r.id, feed

    self.builtins = {}
    rows = conn.database.db.view('feedie/feed')
    summary = {}
    for id, summ in Feed.get_summaries(keys=[r.id for r in rows]):
      summary[id] = summ

    zero = lambda:dict(total=0, read=0)
    self.feeds = dict(map(feed_from_row, rows))
    self.max_pos = max([0] + [x.pos for x in self.feeds.values()])

  @property
  def feed_ids(self):
    return self.feeds.keys()

  def add_builtin(self, source):
    self.builtins[source.id] = source
    getattr(source, 'added_to', lambda x: None)(self)
    self.emit('builtin-added', source)
    self.emit('source-added', source)

  def add_source(self, feed):
    self.feeds[feed.id] = feed
    getattr(feed, 'added_to', lambda x: None)(self)
    self.emit('feed-added', feed)
    self.emit('source-added', feed)
    return self.feeds[feed.id]

  def remove_feed(self, feed):
    if feed.id in self.feeds:
      del self.feeds[feed.id]
      self.emit('feed-removed', feed)
      self.emit('source-removed', feed)

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
    feed = Feed(rec, summary)
    feed.connect('deleted', self.feed_deleted)
    feed = self.add_source(feed)
    for post in ifeed.posts:
      feed.save_post(post)
    return feed

  def feed_deleted(self, feed, event):
    self.remove_feed(feed)

class Feed(Model):
  def __init__(self, doc, summary):
    self.doc = doc
    self.summary = summary

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
      self.emit('post-added', post_id)
      self.summary = Feed.get_summary(key=self.id)
      self.emit('summary-changed')
    except couchdb.client.ResourceConflict:
      return self.save_post(ipost, conn.database.db[post_id])

  @property
  def id(self):
    return self.doc['_id']

  def post_summaries(self):
    rows = conn.database.db.view('feedie/feed_post', key=self.id)
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
    self.emit('deleted')

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
