import re
import cgi
import time
import couchdb
import urlparse
import hashlib
import feedparser
import calendar
import traceback
from collections import defaultdict, namedtuple
from desktopcouch.records.record import Record
from twisted.internet import reactor, defer, threads
from twisted.internet import error as twisted_error

from feedie import http
from feedie import util
from feedie import incoming
from feedie.attrdict import attrdict

ONE_WEEK = 7 * 24 * 60 * 60

DELETED_POST_KEYS = tuple('''

  _id _rev type feed_id feed_subscribed_at feed_deleted updated_at
  read_updated_at

'''.split())

class Transfer(object):
  __slots__ = 'progress total'.split()

  def __init__(self, progress=0, total=0):
    self.progress = progress
    self.total = total

class BodyHeadersHack(object):
  def __init__(self, body, url):
    self.body = body
    self.url = url
    self.href = url

  def read(self):
    return self.body

def parse_feed(body, uri):
  return threads.deferToThread(feedparser.parse, BodyHeadersHack(body, uri))

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

INT_PATTERN = re.compile(r'^-?[0-9]+$')
def parse_http_datetime(s):
  try:
    if INT_PATTERN.match(s):
      return int(time.time()) + int(s)
    return int(calendar.timegm(feedparser._parse_date(s)))
  except:
    return 0

class SignalRegistry(object):
  def __init__(self):
    self.map = {}

  def __getitem__(self, name):
    return self.map.setdefault(name, {})

  def register(self, name, handler):
    def unregister():
      del self[name][id]
    assert callable(handler)
    id = object()
    self[name][id] = handler
    return unregister

  def handlers(self, *names):
    return sum([self[name].values() for name in names], [])

class Model(object):
  def __model_init(self):
    if not hasattr(self, 'registry'):
      self.registry = SignalRegistry()

  def connect(self, name, handler):
    self.__model_init()
    return self.registry.register(name, handler)

  def emit(self, name, *args, **kwargs):
    self.__model_init()
    for handler in self.registry.handlers(name, '*'):
      reactor.callLater(0, handler, self, name, *args, **kwargs)

class UnreadNewsSource(Model):
  def __init__(self, db):
    self.db = db
    self.sources = None
    self.posts = {}
    self.summary = dict(total=0, read=0, starred_total=0, starred_read=0)

  def added_to(self, sources):
    def post_changed(sources, event_name, feed, post, field_name=None):
      if field_name == 'read':
        if not post.read:
          self.posts[post._id] = post
          self.emit('posts-added', [post])

          self.summary['total'] += 1
          if post.starred:
            self.summary['starred_total'] += 1

        else:
          del self.posts[post._id]
          self.emit('post-removed', post)

          self.summary['total'] -= 1
          if post.starred:
            self.summary['starred_total'] -= 1

        self.emit('summary-changed')

    def posts_added(sources, event_name, feed, posts):
      added_here = []
      for post in posts:
        if not post.read:
          if post._id not in self.posts:
            self.posts[post._id] = post
            added_here.append(post)
            self.summary['total'] += 1
            if post.starred:
              self.summary['starred_total'] += 1
      self.emit('posts-added', added_here)
      self.emit('summary-changed')

    def post_removed(sources, event_name, feed, post):
      if post._id in self.posts:
        del self.posts[post._id]
        self.emit('post-removed', post)
        self.summary['total'] -= 1
        if post.starred:
          self.summary['starred_total'] -= 1
        self.emit('summary-changed')

    self.sources = sources
    sources.connect('posts-added', posts_added)
    sources.connect('post-removed', post_removed)
    sources.connect('post-changed', post_changed)
    self.update_summary()

  def update_summary(self):
    self.summary = dict(total=0, read=0, starred_total=0, starred_read=0)
    if self.sources:
      for feed in self.sources.subscribed_feeds:
        self.summary['total'] += feed.summary['total']
        self.summary['read'] += feed.summary['read']
    self.emit('summary-changed')

  @property
  def id(self):
    return 'unread-news'

  @property
  def error(self):
    return None

  @property
  def can_refresh(self):
    return False # TODO change this

  # 0 means no transfers,
  # -1 means indeterminate state,
  # 1-100 mean percentage
  @property
  def progress(self):
    return 0

  @defer.inlineCallbacks
  def post_summaries(self):
    def group(rows):
      map = {}
      for row in rows:
        map.setdefault(row['value']['feed_id'], []).append(row['value'])
      return map

    rows = yield self.db.view('feedie/unread_posts',
        keys=self.sources.feed_ids)
    by_feed = group(rows)
    self.posts = {}
    for feed_id, docs in by_feed.items():
      feed = self.get_feed(feed_id)
      posts = feed.upsert_posts(docs, update_summary=False)
      self.posts.update(dict([(post._id, post) for post in posts]))
    defer.returnValue(self.posts.values())

  def get_feed(self, feed_id):
    return self.sources.get_feed(feed_id)

  def get_post(self, post_id):
    feed = self.get_feed(feed_id)
    return feed.posts[post_id]

  @property
  def sort_key(self):
    return [0, 0, '']

  @property
  def title(self):
    return 'Unread News'

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

class StarredNewsSource(Model):
  def __init__(self, db):
    self.db = db
    self.sources = None
    self.posts = {}
    self.summary = dict(total=0, read=0, starred_total=0, starred_read=0)

  def added_to(self, sources):
    def post_changed(sources, event_name, feed, post, field_name=None):
      if field_name == 'starred':
        if post.starred:
          self.posts[post._id] = post
          self.emit('posts-added', [post])

          self.summary['total'] += 1
          self.summary['starred_total'] += 1
          if post.read:
            self.summary['read'] += 1
            self.summary['starred_read'] += 1

        else:
          del self.posts[post._id]
          self.emit('post-removed', post)

          self.summary['total'] -= 1
          self.summary['starred_total'] -= 1
          if post.read:
            self.summary['read'] -= 1
            self.summary['starred_read'] -= 1

        self.emit('summary-changed')

      elif field_name == 'read' and post.starred:
        if post.read:
          self.summary['read'] += 1
          self.summary['starred_read'] += 1
        else:
          self.summary['read'] -= 1
          self.summary['starred_read'] -= 1
        self.emit('summary-changed')

    def posts_added(sources, event_name, feed, posts):
      added_here = []
      for post in posts:
        if post.starred:
          if post._id not in self.posts:
            self.posts[post._id] = post
            added_here.append(post)
            self.summary['total'] += 1
            self.summary['starred_total'] += 1
            if post.read:
              self.summary['read'] += 1
              self.summary['starred_read'] += 1
      self.emit('posts-added', added_here)
      self.emit('summary-changed')

    def post_removed(sources, event_name, feed, post):
      if post._id in self.posts:
        del self.posts[post._id]
        self.emit('post-removed', post)
        self.summary['total'] -= 1
        self.summary['starred_total'] -= 1
        if post.read:
          self.summary['read'] -= 1
          self.summary['starred_read'] -= 1
        self.emit('summary-changed')

    self.sources = sources
    sources.connect('posts-added', posts_added)
    sources.connect('post-removed', post_removed)
    sources.connect('post-changed', post_changed)
    #self.update_summary()

  def update_summary(self):
    self.summary = dict(total=0, read=0, starred_total=0, starred_read=0)
    if self.sources:
      for feed in self.sources.subscribed_feeds:
        self.summary['total'] += feed.summary['starred_total']
        self.summary['read'] += feed.summary['starred_read']
    self.emit('summary-changed')

  @property
  def id(self):
    return 'starred-items'

  @property
  def error(self):
    return None

  @property
  def can_refresh(self):
    return False # TODO change this

  # 0 means no transfers,
  # -1 means indeterminate state,
  # 1-100 mean percentage
  @property
  def progress(self):
    return 0

  @defer.inlineCallbacks
  def post_summaries(self):
    def row_to_entry(row):
      doc = row['value']
      return row['id'], self.get_feed(doc['feed_id']).post(doc)
    rows = yield self.db.view('feedie/starred_posts')
    self.posts = dict(map(row_to_entry, rows))
    defer.returnValue(self.posts.values())

  def get_feed(self, feed_id):
    return self.sources.get_feed(feed_id)

  def get_post(self, post_id):
    feed = self.get_feed(feed_id)
    return feed.posts[post_id]

  @property
  def sort_key(self):
    return [0, 1, '']

  @property
  def title(self):
    return 'Starred Items'

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
  def __init__(self, db, http_client, icon_http_client):
    self.db = db
    self.http_client = http_client
    self.icon_http_client = icon_http_client
    self.builtins = {}
    self.feeds = {}
    self.subscribed_feeds = []
    self.doc = dict(_id=self._id)
    self.builtin_order = []
    self.needs_refresh = []

    def post_removed_helper(feed, event_name, post):
      (post.__disconnect_changed or (lambda:None))()
      post.__disconnect_changed = None

      self.emit('post-removed', feed, post)

    def feed_added_helper(sources, event_name, feed):
      def posts_added(feed, event_name, posts):
        def changed(post, event_name, field_name=None):
          self.emit('post-changed', feed, post, field_name)

        for post in posts:
          post.__disconnect_changed = post.connect('changed', changed)

        self.emit('posts-added', feed, posts)

      feed.__disconnect_posts_added = feed.connect('posts-added', posts_added)
      feed.__disconnect_post_removed = feed.connect('post-removed',
          post_removed_helper)

    self.connect('feed-added', feed_added_helper)

    def feed_removed_helper(sources, event_name, feed):
      (feed.__disconnect_posts_added or (lambda:None))()
      feed.__disconnect_posts_added = None

      (feed.__disconnect_post_removed or (lambda:None))()
      feed.__disconnect_post_removed = None

      for post in feed.posts.values():
        post_removed_helper(feed, 'post-removed', post)

    self.connect('feed-removed', feed_removed_helper)

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

    docs = [r['value'] for r in rows]
    self.upsert_feeds(docs, summaries=summaries)

    self.housekeeping()

  @defer.inlineCallbacks
  def housekeeping(self):
    yield self.collect_garbage()
    self.refresh_all()
    reactor.callLater(60, self.housekeeping)

  def refresh_all(self):
    return self.refresh_feeds(self.subscribed_feeds)

  def refresh_feeds(self, feeds):
    order = sorted(feeds, key=lambda x: x.sort_key)
    ds = []
    for feed in order:
      ds.append(feed.refresh())
    return defer.DeferredList(ds)

  @property
  def is_refreshing(self):
    for feed in self.subscribed_feeds:
      if feed.is_refreshing: return True
    return False

  @defer.inlineCallbacks
  def collect_garbage(self):
    if self.is_refreshing: return
    yield self.collect_garbage_posts()
    yield self.collect_garbage_feeds()
    yield self.mark_posts_with_deleted_feeds()
    yield self.delete_empty_redirected_feeds()

  # This code must be careful not to retry modifications.
  @defer.inlineCallbacks
  def collect_garbage_posts(self):
    def modify(doc):
      if doc.get('_rev', None) != revs[doc['_id']]:
        doc.clear()
        return

      read_at = doc.get('read_at', now)

      if doc.get('feed_deleted', False):
        doc['_deleted'] = True
      elif (now - read_at) > ONE_WEEK:
        # Remove most fields to save space. Keep just enough to know the user
        # has read this post before.
        doc2 = doc.copy()
        doc.clear()
        for k in DELETED_POST_KEYS:
          if k in doc2:
            doc[k] = doc2[k]
        doc['deleted_at'] = now
      else:
        doc.clear()

    now = int(time.time())
    revs = {}
    rows = yield self.db.view('feedie/posts_to_gc')
    for row in rows:
      revs[row['id']] = row['value']

    yield self.db.modify_docs(revs.keys(), modify, load_first=True)

  # This code must be careful not to retry modifications.
  #
  # If a feed is deleted, no more posts can appear until the feed is subscribed
  # again. So we ask for deleted feeds, then, for each feed, ask if any posts
  # exist. If no posts exist, we delete the feed. There is no race condition as
  # long as we only delete the feed rev that we originally got.
  @defer.inlineCallbacks
  def collect_garbage_feeds(self):
    def modify(doc):
      if doc.get('_rev', None) == revs[doc['_id']]:
        doc['_deleted'] = True
      else:
        doc.clear()

    revs = {}
    rows = yield self.db.view('feedie/deleted_feeds')
    for row in rows:
      summaries = yield Feed.load_summaries(self.db, [row['id']])
      if summaries:
        id, summary = summaries[0]
      else:
        summary = dict(total=0, read=0, starred_total=0, starred_read=0)
      if summary['total'] == 0:
        revs[row['id']] = row['value']['_rev']

    yield self.db.modify_docs(revs.keys(), modify, load_first=True)

  # This code must be careful not to retry modifications.
  #
  # If a feed is deleted, no more posts can appear until the feed is subscribed
  # again. So we ask for deleted feeds, then, for each feed, ask if any posts
  # exist. If no posts exist, we delete the feed. There is no race condition as
  # long as we only delete the feed rev that we originally got.
  @defer.inlineCallbacks
  def delete_empty_redirected_feeds(self):
    rows = yield self.db.view('feedie/redirected_feeds')
    for row in rows:
      if row['id'] in self.feeds:
        feed = self.get_feed(row['id'])
        if feed.summary['total'] == 0:
          yield feed.delete()

  @defer.inlineCallbacks
  def mark_posts_with_deleted_feeds(self):
    revs = []
    rows = yield self.db.view('feedie/deleted_feeds')
    for row in rows:
      revs.append((row['id'], row['value']['subscribed_at']))

    for feed_id, feed_subscribed_at in revs:
      yield self.mark_posts_feed_is_deleted(feed_id, feed_subscribed_at)

  @defer.inlineCallbacks
  def mark_posts_feed_is_deleted(self, feed_id, feed_subscribed_at):
    def modify(doc):
      doc_rev = doc.get('_rev', None)
      doc_feed_subscribed_at = doc.get('feed_subscribed_at', 0)
      if doc_rev == revs[doc['_id']]:
        doc['feed_deleted'] = True
      elif feed_subscribed_at >= doc_feed_subscribed_at:
        doc['feed_deleted'] = True
      else:
        doc.clear()

    revs = {}
    rows = yield self.db.view('feedie/posts_to_mark_feed_is_deleted',
        keys=[feed_id])
    for row in rows:
      value = row['value']
      revs[value['post_id']] = value['post_rev']

    yield self.db.modify_docs(revs.keys(), modify, load_first=True)

  @property
  def doc(self):
    return self._doc

  @doc.setter
  def doc(self, doc):
    self._doc = doc

  @defer.inlineCallbacks
  def modify(self, modify):
    self.doc = yield self.db.modify_doc(self._id, modify, doc=self.doc)

  @property
  def order(self):
    return self.builtin_order + self.feed_ids

  @property
  def feed_ids(self):
    return [x.id for x in self.subscribed_feeds]

  def add_builtin(self, source):
    self.builtins[source.id] = source
    self.builtin_order.append(source.id)
    source.added_to(self)
    self.emit('builtin-added', source)
    self.emit('sources-added', [source])

  # Retrieves the feeds. If each one does not exist, creates it using an
  # element of default_docs.
  def upsert_feeds(self, default_docs, summaries={}):
    def adapt(default_doc):
      summary = summaries.get(doc['_id'], None)
      feed_id = default_doc['_id']
      if feed_id not in self.feeds:
        feed = self.feeds[feed_id] = Feed(self, default_doc, summary)
        if feed.subscribed:
          self.subscribed_feeds.append(feed)
        feed.added_to(self)
        self.emit('feed-added', feed)
        feed.connect('deleted', self.feed_deleted)
        is_new = True
      else:
        is_new = False

      return self.feeds[feed_id], is_new

    feeds = []
    new_feeds = []
    for doc in default_docs:
      feed, is_new = adapt(doc)
      feeds.append(feed)
      if is_new:
        new_feeds.append(feed)

    self.emit('sources-added', new_feeds)

    return feeds

  def get_feed(self, feed_id):
    return self.feeds[feed_id]

  def can_remove(self, source):
    return source.id in self.feeds

  def __iter__(self):
    return iter([self[id] for id in self.order if id in self])

  def __getitem__(self, id):
    if id in self.builtins:
      return self.builtins[id]
    if id in self.feeds:
      return self.feeds[id]
    raise KeyError(id)

  def __contains__(self, id):
    return id in self.builtins or id in self.feeds

  @defer.inlineCallbacks
  def add_subscriptions(self, subs):
    now = int(time.time())
    def modify(doc):
      sub = by_id[doc['_id']]
      defaults = sub.get('defaults', {})
      uri = http.normalize_uri(sub['uri'])
      doc.setdefault('title', uri[7:] if uri.startswith('http://') else uri)
      for k, v in defaults.items():
        doc.setdefault(k, v)
      doc['type'] = 'feed'
      doc['source_uri'] = uri
      doc['subscribed_at'] = now

    by_id = {}
    for sub in subs:
      feed_id = short_hash(sub['uri'])
      by_id[feed_id] = sub

    docs = yield self.db.modify_docs(by_id.keys(), modify)
    feeds = self.upsert_feeds(docs)
    for feed, doc in zip(feeds, docs):
      feed.doc = doc

    defer.returnValue(feeds)

  def feed_deleted(self, feed, event):
    if feed in self.subscribed_feeds:
      self.subscribed_feeds.remove(feed)
    self.emit('feed-removed', feed)
    self.emit('source-removed', feed)

  @defer.inlineCallbacks
  def mark_posts_as(self, posts, read):
    now = int(time.time())
    if read:
      def modify(doc):
        when = doc.get('updated_at', 0)
        doc['read_updated_at'] = when
        doc['read_at'] = now
    else:
      def modify(doc):
        if 'read_updated_at' in doc:
          del doc['read_updated_at']
        if 'read_at' in doc:
          del doc['read_at']

    ids = [post._id for post in posts]
    docs = [post.doc.copy() for post in posts]
    docs = yield self.db.modify_docs(ids, modify, docs=docs)

    # update each post with current doc from the db
    for post, doc in zip(posts, docs):
      post.doc = doc

count_load_summaries = 0

class Feed(Model):
  is_refreshing = False

  def __init__(self, sources, doc, summary=None):
    self.sources = sources
    self.db = sources.db
    self.doc = doc
    self.posts = {}
    self.summary = summary or dict(total=0, read=0, starred_total=0, starred_read=0)
    self.load_favicon()

  @defer.inlineCallbacks
  def load_post(self, post_id):
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
    defer.returnValue(dict(total=0, read=0, starred_total=0, starred_read=0))

  @property
  def transfers(self):
    self._transfers = getattr(self, '_transfers', [])
    return self._transfers

  # 0 means no transfers,
  # -1 means indeterminate state,
  # 1-100 mean percentage
  @property
  def progress(self):
    if not self.transfers: return 0
    progress, total = 0, 0
    for t in self.transfers:
      if not t.total: return -1
      progress += t.progress
      total += t.total
    return 100 * progress / total

  @defer.inlineCallbacks
  def fetch(self, uri, http=None, icon=False):
    def on_connecting(*args):
      self.transfers.append(transfer)
      transfer.progress = 0
      transfer.total = 0
      self.emit('summary-changed')
    def on_connected(*args):
      transfer.progress = 0
      transfer.total = 0
      self.emit('summary-changed')
    def on_status(*args):
      transfer.progress = 0
      transfer.total = 0
      self.emit('summary-changed')
    def on_headers(*args):
      transfer.progress = 0
      transfer.total = 0
      self.emit('summary-changed')
    def on_body(event_name, progress, total):
      transfer.progress = progress
      transfer.total = total
      self.emit('summary-changed')

    def on_complete(x):
      try:
        if transfer in self.transfers:
          self.transfers.remove(transfer)
        self.emit('summary-changed')
      except:
        pass
      return x

    headers = {}
    if http is None: http = {}
    if 'last-modified' in http:
      headers['if-modified-since'] = http['last-modified']
    if 'etag' in http:
      headers['if-none-match'] = http['etag']
    if icon:
      client = self.sources.icon_http_client
    else:
      client = self.sources.http_client
    d = client.request(uri, headers=headers)
    transfer = Transfer(progress=0, total=0)
    d.addListener('connecting', on_connecting)
    d.addListener('connected', on_connected)
    d.addListener('status', on_status)
    d.addListener('headers', on_headers)
    d.addListener('body', on_body)
    d.addCallback(on_complete)

    @d.addErrback
    def d(reason):
      if transfer in self.transfers:
        self.transfers.remove(transfer)
      raise reason

    defer.returnValue((yield d))

  @defer.inlineCallbacks
  def modify(self, modify):
    self.doc = yield self.db.modify_doc(self.id, modify, doc=self.doc)

  @staticmethod
  def extract_max_age(response):
    h = response.headers
    if 'cache-control' not in h: return None
    parts = [x.strip() for x in h['cache-control'].split(',')]
    for part in parts:
      if part.startswith('max-age='):
        return int(part[8:])
    return None

  @staticmethod
  def modify_http(http, response, min_max_age):
    now = int(time.time())
    if 'last-modified' in response.headers:
      http['last-modified'] = response.headers['last-modified']
    if 'etag' in response.headers:
      http['etag'] = response.headers['etag']

    max_age = Feed.extract_max_age(response)
    if max_age is not None:
      req_date = parse_http_datetime(response.headers.get('date', now))
      http['expires_at'] = req_date + max_age
    elif 'expires' in response.headers:
      http['expires_at'] = parse_http_datetime(response.headers['expires'])
    else:
      http['expires_at'] = now

    # wait at least 30 min
    http['expires_at'] = max(http['expires_at'], now + min_max_age)

  @defer.inlineCallbacks
  def save_ifeed(self, ifeed, response):
    def modify(doc):
      doc['link'] = ifeed.link
      doc['title'] = ifeed.title
      doc['subtitle'] = ifeed.subtitle
      doc['author_detail'] = ifeed.author_detail
      doc['updated_at'] = ifeed.updated_at
      if 'error' in doc: del doc['error']
      self.modify_http(doc.setdefault('http', {}), response, 1800)

    yield self.modify(modify)
    yield self.save_iposts(ifeed.posts)
    defer.returnValue(None)

  @defer.inlineCallbacks
  def save_headers(self, name, response, min_max_age, **extra):
    def modify(doc):
      self.modify_http(doc.setdefault(name, {}), response, min_max_age)
      for k, v in extra.items():
        doc[k] = v

    yield self.modify(modify)
    defer.returnValue(None)

  @property
  def expires_at(self):
    return self.doc.get('http', {}).get('expires_at', 0)

  @property
  def icon_expires_at(self):
    return self.doc.get('icon_http', {}).get('expires_at', 0)

  @property
  def ready_for_refresh(self):
    now = int(time.time())
    return now > self.expires_at

  @property
  def ready_for_refresh_favicon(self):
    now = int(time.time())
    return now > self.icon_expires_at

  @defer.inlineCallbacks
  def save_error(self, error, **extra):
    now = int(time.time())
    def modify(doc):
      doc['error'] = error
      http = doc.setdefault('http', {})
      http['expires_at'] = now + 1800 # cache the error for 1/2 hour
      for k, v in extra.items():
        doc[k] = v
    yield self.modify(modify)

  @defer.inlineCallbacks
  def redirect(self, link, **extra):
    link = urlparse.urljoin(self.doc['source_uri'], link)
    yield self.save_error('redirect', link=link, **extra)

    if 'user_title' in self.doc:
      extra.setdefault('user_title', self.doc['user_title'])
    sub = dict(uri=link, defaults=extra)
    other = (yield self.sources.add_subscriptions([sub]))[0]
    if self.summary['total'] == 0:
      self.delete()
    other = yield other.refresh()
    defer.returnValue(other)

  @defer.inlineCallbacks
  def refresh(self, force=False):
    if not (force or self.ready_for_refresh):
      if self.ready_for_refresh_favicon:
        self.discover_favicon()
      defer.returnValue(self)
    if self.is_refreshing: defer.returnValue(self)

    try:
      self.is_refreshing = True

      uri = self.doc['source_uri']
      http_info = self.doc.get('http', None)
      try:
        response = yield self.fetch(uri, http_info)
      except http.BadURIError:
        yield self.save_error('bad-uri')
        self.emit('favicon-changed')
        defer.returnValue(self)
      except http.UnsupportedSchemeError:
        yield self.save_error('unsupported-scheme')
        self.emit('favicon-changed')
        defer.returnValue(self)
      except twisted_error.DNSLookupError:
        yield self.save_error('dns')
        self.emit('favicon-changed')
        defer.returnValue(self)
      except twisted_error.TimeoutError:
        yield self.save_error('timeout')
        self.emit('favicon-changed')
        defer.returnValue(self)
      except Exception, ex:
        yield self.save_error('other', detail=traceback.format_exc())
        self.emit('favicon-changed')
        defer.returnValue(self)

      # TODO handle temporary redirects properly
      if response.status.code in (301, 302, 303, 307):
        defer.returnValue((yield self.redirect(response.headers['location'])))

      if response.status.code == 304:
        # update last-modified, etag, etc
        yield self.save_headers('http', response, 1800)
        yield self.discover_favicon()
        defer.returnValue(self)

      uri = self.doc['source_uri']
      parsed = yield parse_feed(response.body, uri)

      if not parsed.version: # not a feed
        if 'links' not in parsed.feed:
          yield self.save_headers('http', response, 1800, error='notafeed')
          defer.returnValue(self)

        links = [x for x in parsed.feed.links if x.rel == 'alternate']

        if not links:
          yield self.save_headers('http', response, 1800, error='notafeed')
          defer.returnValue(self)

        extra = {}
        if 'title' in links[0] and links[0].title:
          extra['title'] = links[0].title
        defer.returnValue((yield self.redirect(links[0].href, **extra)))

      ifeed = incoming.Feed(parsed)
      yield self.save_ifeed(ifeed, response)
      yield self.discover_favicon(ifeed)
      defer.returnValue(self)

    finally:
      self.is_refreshing = False

  @defer.inlineCallbacks
  def discover_favicon(self, ifeed=None):
    # We already got some. Maybe some day we'll try again.
    if 'icon_uri' in self.doc:
      # No yield! We don't want to wait on the result.
      d = self.refresh_favicon()
      return

    uri = yield self.discover_favicon_uri(ifeed)

    def modify(doc):
      doc['icon_uri'] = uri
      doc['icon_http'] = {}

    yield self.modify(modify)

    # No yield! We don't want to wait on the result.
    d = self.refresh_favicon()

  @defer.inlineCallbacks
  def discover_favicon_uri(self, ifeed=None):
    rejected = self.doc.get('rejected_icon_uris', [])

    if ifeed and 'icon' in ifeed:
      if ifeed.icon not in rejected:
        defer.returnValue(ifeed.icon)

    if self.link:
      try:
        response = yield self.fetch(self.link, icon=True)
      except Exception, ex:
        response = None
      # TODO save expires time for this document

      # We don't care about the status code. A 404 page will do just fine.
      if response and response.body:

        # Woo, let's abuse the feed parser to parse html!!!
        try:
          parsed = yield parse_feed(response.body, self.link)
        except Exception, ex:
          parsed = None

        if parsed and parsed.feed and 'links' in parsed.feed:
          links = parsed.feed.links
          uris = [x.href for x in links if x.rel == 'shortcut icon']
          if uris:
            if uris[0] not in rejected:
              defer.returnValue(uris[0])

      guess = urlparse.urljoin(self.link, '/favicon.ico')
      if guess not in rejected:
        defer.returnValue(guess)

    defer.returnValue('')

  @defer.inlineCallbacks
  def refresh_favicon(self):
    if not self.ready_for_refresh_favicon: return

    uri = self.doc.get('icon_uri', None)
    headers = self.doc.get('icon_http', {})

    if not uri: return

    try:
      response = yield self.fetch(uri, headers, icon=True)
    except Exception, ex:
      return

    # update last-modified, etag, etc
    yield self.save_headers('icon_http', response, 86400)

    if response.status.code in (301, 302, 303, 307):
      return # bleh. someday I will try harder

    if response.status.code == 304:
      return

    if response.status.code == 200:
      yield self.put_favicon(response.body)
      return # We win! No more work to do!

  @defer.inlineCallbacks
  def put_favicon(self, favicon_data):
    if hasattr(self, 'favicon_data') and self.favicon_data == favicon_data:
      return
    while True:
      try:
        rev = self.doc['_rev']
        yield self.db.put_attachment(self.id, 'favicon_data', favicon_data, rev)
        break
      except couchdb.client.ResourceConflict:
        self.doc = yield self.db.load_doc(self.id)
    self.doc = yield self.db.load_doc(self.id)
    self.favicon_data = favicon_data
    self.emit('favicon-changed')

  @defer.inlineCallbacks
  def load_favicon(self):
    if '_attachments' not in self.doc: return
    att = self.doc['_attachments']
    if 'favicon_data' not in att: return
    self.favicon_data = yield self.db.get_attachment(self.id, 'favicon_data')
    self.emit('favicon-changed')

  @defer.inlineCallbacks
  def reject_favicon(self):
    def modify(doc):
      if 'icon_uri' not in doc:
        doc.clear()
        return
      uri = doc['icon_uri']
      del doc['icon_uri']
      rejected = doc.setdefault('rejected_icon_uris', [])
      if uri not in rejected:
        rejected.append(uri)

    yield self.modify(modify)

    while True:
      try:
        rev = self.doc['_rev']
        yield self.db.delete_attachment(self.id, 'favicon_data', rev)
        break
      except couchdb.client.ResourceConflict:
        self.doc = yield self.db.load_doc(self.id)
    self.doc = yield self.db.load_doc(self.id)
    self.favicon_data = None
    self.emit('favicon-changed')


  @property
  def can_refresh(self):
    return True

  @property
  def error(self):
    return self.doc.get('error', None)

  def post_changed(self, post, event_name, field_name=None):
    if field_name == 'read':
      new_read = post.read
      old_read = not new_read
      if new_read:
        self.summary['read'] += 1
        if post.starred:
          self.summary['starred_read'] += 1
      else:
        self.summary['read'] -= 1
        if post.starred:
          self.summary['starred_read'] -= 1
      self.emit('summary-changed')
    elif field_name == 'starred':
      self.update_summary()

  # Retrieves the posts. If each one does not exist, creates it using
  # the appropriate element in default_doc.
  def upsert_posts(self, default_docs, update_summary=True):
    posts = []
    new_posts = []
    for default_doc in default_docs:
      post_id = default_doc['_id']
      if post_id not in self.posts:
        post = self.posts[post_id] = Post(default_doc, self)
        post.connect('changed', self.post_changed)

        if update_summary:
          self.summary['total'] += 1
          if post.read:
            self.summary['read'] += 1
          if post.starred:
            self.summary['starred_total'] += 1
            if post.read:
              self.summary['starred_read'] += 1

        new_posts.append(post)
      posts.append(self.posts[post_id])

    if new_posts:
      self.emit('posts-added', new_posts)
      if update_summary:
        self.emit('summary-changed')

    return posts

  # Retrieves the post. If it does not exist, creates one using default_doc.
  def post(self, default_doc):
    return self.upsert_posts([default_doc])[0]

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
      doc['feed_subscribed_at'] = self.x_subscribed_at
      if 'feed_deleted' in doc: del doc['feed_deleted']
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

    posts = self.upsert_posts(docs)
    for post, doc in zip(posts, docs):
      post.doc = doc

  @property
  def id(self):
    return self.doc['_id']

  @property
  def _rev(self):
    return self.doc['_rev']

  @property
  def type(self):
    return self.doc['type']

  @property
  def source_uri(self):
    return self.doc['source_uri']

  @defer.inlineCallbacks
  def check_posts_loaded(self):
    rows = yield self.db.view('feedie/feed_post', key=self.id)
    self.posts = dict([(row['id'], self.post(row['value'])) for row in rows])

  @defer.inlineCallbacks
  def post_summaries(self):
    yield self.check_posts_loaded()
    defer.returnValue(self.posts.values())

  @property
  def sort_key(self):
    return [1, 0, self.title.lower()]

  @property
  def title(self):
    return self.doc.get('user_title', self.doc.get('title', '(unknown title)'))

  @property
  def icon(self):
    error = self.doc.get('error', None)
    if error and error != 'redirect':
      return 'gtk-dialog-error'
    return 'gtk-file'

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

    was = self.x_subscribed_at
    yield self.modify(modify)
    now = self.x_subscribed_at
    if was != now:
      self.emit('changed', 'subscribed_at')

  @property
  def is_deleted(self):
    delat = self.x_deleted_at
    subat = self.x_subscribed_at
    return delat > subat

  @property
  def subscribed(self):
    return not self.is_deleted

  @property
  def stored(self):
    return '_rev' in self.doc

  @defer.inlineCallbacks
  def delete(self):
    if self.stored:
      def modify(doc):
        doc['deleted_at'] = now

        # Forget the expiration times, etc, because our cache will go away.
        doc['http'] = {}
        doc['icon_http'] = {}

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

  @property
  def doc(self):
    return self._doc

  @property
  def _id(self):
    return self.doc['_id']

  @property
  def title(self):
    return self.doc['title']

  @property
  def link(self):
    return self.doc['link']

  @property
  def feed_id(self):
    return self.doc['feed_id']

  @property
  def content(self):
    return self.doc['content']

  @property
  def summary_detail(self):
    return self.doc['summary_detail']

  @property
  def updated_at(self):
    return self.doc['updated_at']

  @doc.setter
  def doc(self, new):
    if not hasattr(self, '_doc'):
      self._doc = attrdict(new)
      return

    old = self._doc
    if old != new:
      self._doc = attrdict(new)
      self.emit('changed', None)
      old_read = old.get('read_updated_at', 0) >= old.get('updated_at', 0)
      new_read = new.get('read_updated_at', 0) >= new.get('updated_at', 0)
      if old_read != new_read:
        self.emit('changed', 'read')

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

  def toggle_read_updated_at(self, sources):
    return sources.mark_posts_as([self], read=not self.read)

  @property
  def read_updated_at(self):
    return self.doc.get('read_updated_at', 0)

  @property
  def read(self):
    return self.read_updated_at >= self.updated_at

  @defer.inlineCallbacks
  def toggle_starred(self):
    def modify(doc):
      doc['starred'] = new_starred

    was_starred = self.starred
    new_starred = not self.starred
    yield self.modify(modify)
    now_starred = self.starred

    if was_starred != now_starred: # always true
      self.emit('changed', 'starred')

  @property
  def starred(self):
    return self.doc.get('starred', False)
