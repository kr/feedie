import couchdb
from datetime import datetime
from desktopcouch.records.record import Record

from feedie import conn
from feedie import util

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
    return [row.value for row in rows]

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
    if feed.id not in self.feeds:
      self.feeds[feed.id] = feed
      self.changed()
    return self.feeds[feed.id]

  def remove_feed(self, feed):
    if feed.id in self.feeds:
      del self.feeds[feed.id]
      self.changed()

  def __iter__(self):
    feeds = sorted(self.feeds.values(), key=lambda x: (-x.pos, x.title, x.id))
    return iter(self.builtins.values() + feeds)

  def __getitem__(self, id):
    return self.builtins[id]

  def subscribe(self, uri, xml):
    rec = None
    try:
      self.max_pos += 1
      doc = {}
      doc['type'] = 'feed'
      doc['title'] = xml.feed.get('title', '(unknown title)')
      doc['pos'] = self.max_pos
      if 'subtitle' in xml: doc['subtitle'] = xml.subtitle
      conn.database.db[uri] = doc
    except couchdb.client.ResourceConflict:
      rec = conn.database.db.get(uri)
      if rec.get('deleted', False):
        rec.deleted = False
        conn.database.db[rec.id] = rec
        rec = None
    rec = rec or conn.database.db.get(uri)
    summary = Feed.get_summary(key=uri)
    feed = self.add_feed(Feed(rec, summary, self))
    for entry in xml.entries:
      feed.save_post(entry)
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

  def save_post(self, xml, doc=None):
    if doc is None: doc = {}
    if 'updated' in xml:
      updated = util.normalize_datetime(xml.updated)
    elif 'published' in xml:
      updated = util.normalize_datetime(xml.published)
    else:
      return
    if doc.get('updated_at', '0000-00-00T00:00:00Z') >= updated: return

    # try real hard to get a useful id for this post
    if 'id' in xml:
      post_id = xml.id
    elif 'link' in xml:
      post_id = xml.link
    else:
      post_id = [self.id, updated]

    print 'syncing', post_id

    doc['type'] = 'post'
    doc['title'] = xml.get('title', '(unknown title)')
    doc['updated_at'] = updated
    doc['feed_id'] = self.id
    if 'link' in xml: doc['link'] = xml.link
    if 'summary' in xml: doc['summary'] = xml.summary
    if 'content' in xml: doc['content'] = xml.content # TODO use less-sanitized
    if 'published' in xml: doc['published_at'] = xml.published
    try:
      conn.database.db[post_id] = doc
      self.summary = Feed.get_summary(key=self.id)
      self.changed()
    except couchdb.client.ResourceConflict:
      return self.save_post(xml, conn.database.db[post_id])

  @property
  def id(self):
    return self.doc['_id']

  def post_summaries(self):
    rows = conn.database.db.view('feedie/feed_post', key=['feed', 0, self.id])
    return [row.value for row in rows]

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
  def is_deleted(self):
    return not not self.doc.get('deleted_at', None)

  def delete(self):
    self.doc['deleted_at'] = datetime.utcnow().isoformat()
    conn.database.db[self.id] = self.doc
    self.changed()
