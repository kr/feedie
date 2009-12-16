import cgi
import time
import couchdb
import urlparse
from collections import defaultdict
from desktopcouch.records.record import Record
from twisted.internet import reactor, defer

from feedie import util
from feedie.attrdict import attrdict

preferred=('text/html', 'application/xhtml+xml', 'text/plain')

def preference_score(item):
  try:
    return preferred[::-1].index(item['type'])
  except ValueError:
    return -1

def detail_html(item):
  if item['type'] in ('text/html', 'application/xhtml+xml'):
    return item['value']
  return cgi.escape(item['value'])

class Model(object):
  def __model_init(self):
    if not hasattr(self, 'handlers'):
      self.handlers = defaultdict(list)

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
  def __init__(self, db):
    self.db = db
    self.sources = None
    self.posts = {}
    self.update_summary()

  def added_to(self, sources):
    def summary_changed(source, event):
      self.update_summary()

    def feed_added(sources, event, feed):
      feed.connect('summary-changed', summary_changed)
      self.update_summary()

    def feed_removed(sources, event, feed):
      self.update_summary()

    self.sources = sources
    sources.connect('feed-added', feed_added)
    sources.connect('feed-removed', feed_removed)
    for feed in sources.feeds.values():
      feed.connect('summary-changed', summary_changed)
    self.update_summary()

  def update_summary(self):
    self.summary = attrdict(total=0, read=0)
    if self.sources:
      for feed in self.sources.feeds.values():
        self.summary.total += feed.summary['total']
        self.summary.read += feed.summary['read']
    self.emit('summary-changed')

  @property
  def id(self):
    return 'all-news'

  @defer.inlineCallbacks
  def post_summaries(self):
    def row_to_entry(row):
      doc = row['value']
      return row['id'], Post(doc, self.get_feed(doc['feed_id']))
    if not self.posts:
      rows = yield self.db.view('feedie/feed_post',
          keys=self.sources.feed_ids)
      self.posts = dict(map(row_to_entry, rows))
    defer.returnValue(self.posts.values())

  def get_feed(self, feed_id):
    self.sources.get_feed(feed_id)

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
  def __init__(self, db):
    self.db = db
    self.builtins = {}
    self.feeds = {}
    self.max_pos = 0

  @defer.inlineCallbacks
  def load(self):
    rows = yield self.db.view('feedie/feed')

    summary_rows = yield Feed.load_summaries(self.db, [r['id'] for r in rows])
    summaries = dict(summary_rows)

    for row in rows:
      feed = self.add_feed(row['value'], summaries.get(row['id'], None))
      feed.connect('deleted', self.feed_deleted)

  @property
  def feed_ids(self):
    return self.feeds.keys()

  def add_builtin(self, source):
    self.builtins[source.id] = source
    source.added_to(self)
    self.emit('builtin-added', source)
    self.emit('source-added', source)

  def add_feed(self, doc, summary=None):
    feed = self.feeds.setdefault(doc['_id'], Feed(self.db, doc, summary))
    feed.doc = doc
    feed.added_to(self)
    self.emit('feed-added', feed)
    self.emit('source-added', feed)
    self.max_pos = max(self.max_pos, feed.pos)
    return feed

  def get_feed(self, feed_id):
    return self.feeds[feed_id]

  def can_remove(self, source):
    return source.id in self.feeds

  def __iter__(self):
    feeds = sorted(self.feeds.values(), key=lambda x: (-x.pos, x.title, x.id))
    return iter(self.builtins.values() + feeds)

  def __getitem__(self, id):
    return self.builtins[id]

  @defer.inlineCallbacks
  def subscribe(self, uri, ifeed):
    def modify(doc):
      doc['type'] = 'feed'
      doc['title'] = ifeed.title
      doc['link'] = ifeed.link
      doc['pos'] = self.max_pos
      doc['subtitle'] = ifeed.subtitle
      doc['author_detail'] = ifeed.author_detail
      doc['subscribed_at'] = now

    self.max_pos += 1
    now = int(time.time())
    doc = yield self.db.modify_doc(uri, modify)

    feed = self.add_feed(doc)
    feed.connect('deleted', self.feed_deleted)
    yield feed.update_summary()
    defer.returnValue(feed)

  def feed_deleted(self, feed, event):
    if feed.id in self.feeds:
      del self.feeds[feed.id]
      self.emit('feed-removed', feed)
      self.emit('source-removed', feed)

class Feed(Model):
  def __init__(self, db, doc, summary=None):
    self.db = db
    self.doc = doc
    self.posts = {}
    self.summary = summary or dict(total=0, read=0)

  @defer.inlineCallbacks
  def get_post(self, post_id):
    x = yield self.get_posts([post_id])
    defer.returnValue(x[0])

  @defer.inlineCallbacks
  def get_posts(self, post_ids):
    yield self.check_posts_loaded()
    defer.returnValue([self.posts[id] for id in post_ids])

  def added_to(self, sources):
    pass

  # Return a list of (uri, summary) pairs. Each summary is a small dictionary.
  @staticmethod
  @defer.inlineCallbacks
  def load_summaries(db, keys):
    rows = yield db.view('feedie/summary', group='true', keys=keys)
    defer.returnValue([(x['key'], x['value']) for x in rows])

  @defer.inlineCallbacks
  def update_summary(self):
    self.summary = yield self.load_summary()

  @defer.inlineCallbacks
  def load_summary(self):
    summaries = yield Feed.load_summaries(self.db, [self.id])
    for id, summary in summaries:
      if id == self.id:
        defer.returnValue(summary)
    defer.returnValue(dict(total=0, read=0))

  def set_posts(self, docs):
    inserted = []
    for doc in docs:
      doc_id = doc['_id']
      if doc_id in self.posts:
        post = self.posts[doc['_id']]
        post.doc = doc
      else:
        post = self.posts[doc_id] = Post(doc, self)
        inserted.append(post)
    self.emit('posts-added', inserted)

  @defer.inlineCallbacks
  def save_posts(self, iposts):
    def modify(doc):
      ipost = by_id[doc['_id']]
      doc['type'] = 'post'
      doc['title'] = ipost.get('title', '(unknown title)')
      doc['updated_at'] = ipost.updated_at
      doc['feed_id'] = self.id
      doc['link'] = ipost.link
      doc['summary_detail'] = ipost.summary_detail
      doc['content'] = ipost.content # TODO use less-sanitized
      doc['author_detail'] = ipost.author_detail
      if 'published' in ipost: doc['published_at'] = ipost.published

    by_id = {}
    for ipost in iposts:
      if not ipost.has_useful_updated_at: continue
      post_id = '%s %s' % (self.id, ipost.id)
      by_id[post_id] = ipost

    docs = yield self.db.modify_docs(by_id.keys(), modify)

    self.set_posts(docs)

    yield self.update_summary()
    self.emit('summary-changed')

  @property
  def id(self):
    return self.doc['_id']

  @defer.inlineCallbacks
  def check_posts_loaded(self):
    if not self.posts:
      rows = yield self.db.view('feedie/feed_post', key=self.id)
      self.posts = dict([(row['id'], Post(row['value'], self)) for row in rows])

  @defer.inlineCallbacks
  def post_summaries(self):
    yield self.check_posts_loaded()
    defer.returnValue(self.posts.values())

  @property
  def title(self):
    return self.doc.get('title', '(unknown title)')

  @property
  def icon(self):
    return 'cancel'

  @property
  def link(self):
    return self.doc.get('link', 'about:blank')

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
  def author_detail(self):
    return self.doc['author_detail']

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

  @defer.inlineCallbacks
  def delete(self):
    def modify(doc):
      doc['deleted_at'] = now

    now = int(time.time())
    self.doc = yield self.db.modify_doc(self.id, modify, doc=self.doc)
    self.emit('deleted')

class Post(Model):
  def __init__(self, doc, feed, complete=False):
    self.doc = doc
    self.feed = feed
    self.complete = complete

  def __getitem__(self, name):
    return self.doc[name]

  def __setitem__(self, name, value):
    self.doc[name] = value

  def __contains__(self, name):
    return name in self.doc

  def __getattr__(self, name):
    if name == '_doc': raise AttributeError(name)
    return getattr(self.doc, name)

  @property
  def doc(self):
    return self._doc

  @doc.setter
  def doc(self, new):
    if not hasattr(self, '_doc'):
      self._doc = attrdict(new)
      return

    old = self._doc
    if old != new:
      self._doc = attrdict(new)
      self.emit('changed')

  def base(self):
    post_domain = urlparse.urlsplit(self.link).netloc
    feed_domain = urlparse.urlsplit(self.feed.link).netloc
    if post_domain == feed_domain:
      return self.link
    return self.feed.link

  @defer.inlineCallbacks
  def load_doc(self):
    if self.complete: return
    doc = yield self.feed.db.load_doc(self._id)
    self.doc = doc
    self.complete = True

  def summary_html(self):
    if self.summary_detail:
      return detail_html(self.summary_detail)
    return None

  @property
  def content_html(self):
    if self.content:
      return detail_html(max(self.content, key=preference_score))
    return None

  @property
  def author_info(self):
    return self['author_detail'] or self.feed.author_detail

  @defer.inlineCallbacks
  def modify(self, modify):
    self.doc = yield self.db.modify_doc(self._id, modify, doc=self.doc)

  @defer.inlineCallbacks
  def set_read(self, is_read):
    def modify(doc):
      doc['read'] = is_read

    yield self.modify(modify)

  @property
  def read(self):
    return self.doc.get('read', False)

  @property
  def starred(self):
    return self.doc.get('starred', False)
