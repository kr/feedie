import cgi
import time
import couchdb
import urlparse
import hashlib
import feedparser
import calendar
from collections import defaultdict
from desktopcouch.records.record import Record
from twisted.internet import reactor, defer

from feedie import util
from feedie import fetcher
from feedie import incoming
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

# Never change this.
def short_hash(s):
  return hashlib.sha1(s).hexdigest()[:16]

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
      return row['id'], self.get_feed(doc['feed_id']).post(doc)
    if not self.posts:
      rows = yield self.db.view('feedie/feed_post',
          keys=self.sources.feed_ids)
      self.posts = dict(map(row_to_entry, rows))
    defer.returnValue(self.posts.values())

  def get_feed(self, feed_id):
    return self.sources.get_feed(feed_id)

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
    self.doc = dict(_id=self._id)
    self.builtin_order = []

  @property
  def _id(self):
    return 'sources'

  @defer.inlineCallbacks
  def load(self):
    try:
      self.doc = yield self.db.load_doc(self._id)
    except couchdb.client.ResourceNotFound, err:
      # Brand new database!
      pass

    rows = yield self.db.view('feedie/feed')

    summary_rows = yield Feed.load_summaries(self.db, [r['id'] for r in rows])
    summaries = dict(summary_rows)

    for row in rows:
      summary = summaries.get(row['id'], None)
      self.feed(row['value'], summary=summary)

  @property
  def doc(self):
    return self._doc

  @doc.setter
  def doc(self, doc):
    self._doc = doc

    # remove duplicates from feed order
    self.feed_order_set = set()
    order = self.feed_order[:]
    self.feed_order[:] = []
    for id in order:
      if id not in self.feed_order_set:
        self.feed_order_set.add(id)
        self.feed_order.append(id)

  @defer.inlineCallbacks
  def modify(self, modify):
    self.doc = yield self.db.modify_doc(self._id, modify, doc=self.doc)

  @defer.inlineCallbacks
  def prepend_to_feed_order(self, source_id):
    def modify(doc):
      doc.setdefault('feed_order', []).insert(0, source_id)
    if source_id not in self.feed_order_set:
      yield self.modify(modify)

  @defer.inlineCallbacks
  def remove_from_feed_order(self, source_id):
    def modify(doc):
      doc['feed_order'].remove(source_id)
    yield self.modify(modify)

  @property
  def feed_order(self):
    return self.doc.get('feed_order', [])

  @property
  def order(self):
    return self.builtin_order + self.feed_order

  @property
  def feed_ids(self):
    return self.feeds.keys()

  def add_builtin(self, source):
    self.builtins[source.id] = source
    self.builtin_order.append(source.id)
    source.added_to(self)
    self.emit('builtin-added', source)
    self.emit('source-added', source)

  # Retrieves the feed. If it does not exist, creates one using default_doc.
  def feed(self, default_doc, summary=None):
    def added(x):
      self.emit('feed-added', feed)
      self.emit('source-added', feed)
      feed.connect('deleted', self.feed_deleted)

    feed_id = default_doc['_id']
    if feed_id not in self.feeds:
      feed = self.feeds[feed_id] = Feed(self.db, default_doc, summary)
      feed.added_to(self)
      d = self.prepend_to_feed_order(feed_id)
      d.addCallback(added)

    return self.feeds[feed_id]

  def get_feed(self, feed_id):
    return self.feeds[feed_id]

  def get_source(self, source_id):
    if source_id in self.builtins:
      return self.builtins[source_id]
    if source_id in self.feeds:
      return self.feeds[source_id]
    raise KeyError(source_id)

  def can_remove(self, source):
    return source.id in self.feeds

  def __iter__(self):
    return iter([self.get_source(id) for id in self.order])

  def __getitem__(self, id):
    return self.builtins[id]

  @defer.inlineCallbacks
  def subscribe(self, uri, defaults={}):
    now = int(time.time())
    doc = dict(
      title = uri,
    )
    doc.update(defaults,
      _id = short_hash(uri),
      source_uri = uri,
      subscribed_at = now,
    )
    feed = self.feed(doc)
    yield feed.refresh()
    if feed.type == 'page' and feed.link:
      yield feed.delete()
      feed2 = yield self.subscribe(feed.link, defaults=dict(title=feed.title))
      defer.returnValue(feed2)
    feed.set_subscribed_at(now)
    defer.returnValue(feed)

  def feed_deleted(self, feed, event):
    def success(x):
      self.emit('feed-removed', feed)
      self.emit('source-removed', feed)

    if feed.id in self.feeds:
      del self.feeds[feed.id]
      d = self.remove_from_feed_order(feed.id)
      d.addCallback(success)

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
    old = self.summary
    self.summary = yield self.load_summary()
    if self.summary != old:
      self.emit('summary-changed')

  @defer.inlineCallbacks
  def load_summary(self):
    summaries = yield Feed.load_summaries(self.db, [self.id])
    for id, summary in summaries:
      if id == self.id:
        defer.returnValue(summary)
    defer.returnValue(dict(total=0, read=0))

  @property
  def transfers(self):
    self._transfers = getattr(self, '_transfers', [])
    return self._transfers

  @property
  def progress(self):
    return 0

  @defer.inlineCallbacks
  def fetch(self):
    def on_fetch(*args):
      print args
    def on_connected(*args):
      print args
    def on_status(*args):
      print args
    def on_headers(*args):
      print args
    def on_body(*args):
      print args

    uri = self.doc['source_uri']
    headers = {}
    if 'http' in self.doc:
      http = self.doc['http']
      if 'last-modified' in http:
        headers['if-modified-since'] = http['last-modified']
      if 'etag' in http:
        headers['if-none-match'] = http['etag']
    d = fetcher.fetch(uri, headers=headers)
    d.addListener('fetch', on_fetch)
    d.addListener('connected', on_connected)
    d.addListener('status', on_status)
    d.addListener('headers', on_headers)
    d.addListener('body', on_body)
    defer.returnValue((yield d))

  @defer.inlineCallbacks
  def modify(self, modify):
    self.doc = yield self.db.modify_doc(self.id, modify, doc=self.doc)

  @defer.inlineCallbacks
  def save_ifeed(self, ifeed, response):
    def modify(doc):
      doc['type'] = 'feed'
      doc['link'] = ifeed.link
      doc['title'] = ifeed.title
      doc['subtitle'] = ifeed.subtitle
      doc['author_detail'] = ifeed.author_detail
      doc['updated_at'] = ifeed.updated_at
      http = doc.setdefault('http', {})
      if 'last-modified' in response.headers:
        http['last-modified'] = response.headers['last-modified']
      if 'etag' in response.headers:
        http['etag'] = response.headers['etag']

    yield self.modify(modify)
    yield self.save_iposts(ifeed.posts)
    defer.returnValue(None)

  @defer.inlineCallbacks
  def save_headers(self, response):
    def modify(doc):
      http = doc.setdefault('http', {})
      if 'last-modified' in response.headers:
        http['last-modified'] = response.headers['last-modified']
      if 'etag' in response.headers:
        http['etag'] = response.headers['etag']

    yield self.modify(modify)
    defer.returnValue(None)

  @defer.inlineCallbacks
  def ready_for_refresh(self):
    return True

  @defer.inlineCallbacks
  def refresh(self):
    if not self.ready_for_refresh: return

    response = yield self.fetch()

    if response.status.code in (301, 302, 303, 307):
      self.doc['type'] = 'page'
      self.doc['link'] = response.headers['location']
      return

    if response.status.code == 304:
      yield self.save_headers(response) # update last-modified, etag, etc
      return

    parsed = feedparser.parse(response.body)

    if not parsed.version: # not a feed
      self.doc['type'] = 'page'
      if 'links' in parsed.feed:
        links = [x for x in parsed.feed.links if x.rel == 'alternate']
        self.doc['link'] = links[0].href
        if 'title' in links[0] and links[0].title:
          self.doc['title'] = links[0].title
      return

    ifeed = incoming.Feed(parsed)
    yield self.save_ifeed(ifeed, response)
    return

  def post_changed(self, post, event_name, field_name=None):
    if field_name == 'read':
      self.update_summary()

  # Retrieves the post. If it does not exist, creates one using default_doc.
  def post(self, default_doc):
    post_id = default_doc['_id']
    if post_id not in self.posts:
      post = self.posts[post_id] = Post(default_doc, self)
      post.connect('changed', self.post_changed)
      self.emit('post-added', post)
    return self.posts[post_id]

  def update_post(self, doc):
    post = self.post(doc)
    post.doc = doc

  @defer.inlineCallbacks
  def save_iposts(self, iposts):
    def modify(doc):
      ipost = by_id[doc['_id']]
      if doc.get('updated_at', 0) >= ipost.updated_at:
        doc.clear() # don't bother saving a new version of this
        return

      doc['type'] = 'post'
      doc['title'] = ipost.get('title', '(unknown title)')
      doc['updated_at'] = ipost.updated_at
      doc['feed_id'] = self.id
      doc['link'] = ipost.link
      doc['summary_detail'] = ipost.summary_detail
      doc['content'] = ipost.content # TODO use less-sanitized
      doc['author_detail'] = ipost.author_detail
      if 'published' in ipost: doc['published_at'] = ipost.published
      doc['contributors'] = ipost.contributors
      doc['tags'] = ipost.tags
      doc['comments'] = ipost.comments

    by_id = {}
    for ipost in iposts:
      if not ipost.has_useful_updated_at: continue
      post_id = short_hash('%s %s' % (self.id, ipost.id))
      by_id[post_id] = ipost

    docs = yield self.db.modify_docs(by_id.keys(), modify)

    for doc in docs:
      self.update_post(doc)

    yield self.update_summary()

  @property
  def id(self):
    return self.doc['_id']

  @property
  def type(self):
    return self.doc['type']

  @defer.inlineCallbacks
  def check_posts_loaded(self):
    if not self.posts:
      rows = yield self.db.view('feedie/feed_post', key=self.id)
      self.posts = dict([(row['id'], self.post(row['value'])) for row in rows])

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
    return self.doc.get('link', '')

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
  def author_detail(self):
    return self.doc['author_detail']

  @property
  def x_deleted_at(self):
    return self.doc.get('deleted_at', 0)

  @property
  def x_subscribed_at(self):
    return self.doc.get('subscribed_at', 0)

  @defer.inlineCallbacks
  def set_subscribed_at(self, when=None):
    def modify(doc):
      doc['subscribed_at'] = when

    if when is None:
      when = int(time.time())

    if self.x_subscribed_at == when:
      return

    #was = self.x_subscribed_at
    yield self.modify(modify)
    #now = self.x_subscribed_at
    #if was != now:
    #  self.emit('changed', 'subscribed_at')

  @property
  def is_deleted(self):
    delat = self.x_deleted_at
    subat = self.x_subscribed_at
    return delat > subat

  @property
  def stored(self):
    return '_rev' in self.doc

  @defer.inlineCallbacks
  def delete(self):
    if self.stored:
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
      self.emit('changed', None)

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
    self.doc = yield self.feed.db.modify_doc(self._id, modify, doc=self.doc)

  @defer.inlineCallbacks
  def set_read_at(self, when=None):
    def modify(doc):
      doc['read_at'] = when

    if when is None:
      when = int(time.time())
    was_read = self.read
    yield self.modify(modify)
    now_read = self.read

    if was_read != now_read:
      self.emit('changed', 'read')

  @property
  def read_at(self):
    return self.doc.get('read_at', 0)

  @property
  def read(self):
    return self.read_at > self.updated_at

  @property
  def starred(self):
    return self.doc.get('starred', False)
