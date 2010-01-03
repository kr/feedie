import re
import gtk
import time
import gobject
from twisted.internet import reactor, defer

from feedie import images
from feedie import util

class PostsTreeModel(gtk.GenericTreeModel):
  __gsignals__ = dict(sorted=(gobject.SIGNAL_RUN_LAST, gobject.TYPE_NONE, ()))

  strip = re.compile('<[^>]*?>')

  columns = (
      ('title',       str),
      ('age',         str),
      ('pretty_date', str),
      ('star',        gtk.gdk.Pixbuf),
      ('read_image',  gtk.gdk.Pixbuf),
      ('read',        bool),
      ('weight',      int),
      ('post_id',     str),
      ('feed_id',     str),
  )

  @classmethod
  def colnum(clas, name):
    return [x[0] for x in clas.columns].index(name)

  def __init__(self, feed):
    gtk.GenericTreeModel.__init__(self)
    self.feed = feed
    self.docs = {}
    self.order = []
    self.refs = {}
    self.sort_column_ids = []
    self.sort_direction = gtk.SORT_ASCENDING

  def _insert_docs(self, docs):
    for doc in docs:
      id = doc._id
      if id in self.docs: return
      n = len(self.order)
      self.order.append(id)
      self.docs[id] = doc
      self.refs[id] = n
      self.row_inserted(n, self.get_iter(n))
      doc.connect('changed', self.post_changed)
    self._sort()

  def post_changed(self, post, event_name, field_name=None):
    n = self.on_get_path(post._id)
    self.row_changed(n, self.get_iter(n))

  def posts_added(self, feed, event_name, posts):
    self._insert_docs(posts)

  def post_removed(self, *args):
    # Don't remove the post now -- it's jarring. When the tree-model gets
    # created next time, the post will be absent.
    pass

  @defer.inlineCallbacks
  def load(self):
    posts = yield self.feed.post_summaries()
    self._insert_docs(posts)

  def column_title(self, doc):
    return self.strip.sub('', doc.title).replace('\r', '').replace('\n', '')

  def column_pretty_date(self, doc):
    now = time.time()
    year = time.gmtime(now).tm_year
    t = time.gmtime(doc.updated_at)
    if t.tm_year != year:
      return time.strftime('%d %b %Y', t)
    if abs(now - doc.updated_at) > 82800: # 23 Hours
      return time.strftime('%d %b', t)
    return time.strftime('%I:%M %p', t).lstrip('0').lower()

  def column_age(self, doc):
    return -doc.updated_at

  def column_read_image(self, doc):
    read = doc.read
    return images.get_pixbuf(('dot', 'blank')[read])

  def column_read(self, doc):
    return bool(doc.read)

  def column_star(self, doc):
    starred = doc.starred
    return images.get_pixbuf(('hollow-star', 'star')[starred])

  def column_weight(self, doc):
    return (700, 400)[doc.read]

  def column_post_id(self, doc):
    return doc._id

  def column_feed_id(self, doc):
    return doc.feed_id

  def on_get_flags(self):
    return gtk.TREE_MODEL_LIST_ONLY|gtk.TREE_MODEL_ITERS_PERSIST

  def on_get_n_columns(self):
    return len(self.columns)

  def on_get_column_type(self, index):
    return self.columns[index][1]

  def on_get_iter(self, path):
    try:
      return self.order[path[0]]
    except IndexError:
      return None

  def on_get_path(self, rowref):
    return self.refs[rowref]

  def doc_value(self, doc, column):
    colname, type = self.columns[column]
    return getattr(self, 'column_' + colname)(doc)

  def on_get_value(self, rowref, column):
    doc = self.docs[rowref]
    return self.doc_value(doc, column)

  def on_iter_next(self, rowref):
    try:
      return self.order[self.refs[rowref] + 1]
    except IndexError:
      return None

  def on_iter_children(self, parent):
    if parent: return None
    if not self.order: return None
    return self.order[0]

  def on_iter_has_child(self, rowref):
    return False

  def on_iter_n_children(self, rowref):
    if rowref: return 0
    return len(self.order)

  def on_iter_nth_child(self, parent, n):
    if parent: return None
    try:
      return self.order[n]
    except IndexError:
      return None

  def on_iter_parent(self, child):
    return None

  def _column_sort_key(self, x):
    i, doc = x
    return [self.doc_value(doc, n) for n in self.sort_column_ids]

  def sort(self, column_ids, direction=gtk.SORT_ASCENDING):
    column_ids = util.flatten([column_ids])
    assert(column_ids)
    for col_id in column_ids:
      if col_id in self.sort_column_ids:
        self.sort_column_ids.remove(col_id)
    self.sort_column_ids[:0] = column_ids
    self.sort_direction = direction
    self._sort()
    self.emit('sorted') # only emit this when we actually change the sort

  def _sort(self):
    perm = [(i, self.docs[id]) for i, id in enumerate(self.order)]
    perm.sort(key=self._column_sort_key,
              reverse=(self.sort_direction == gtk.SORT_DESCENDING))
    self._reorder([r[0] for r in perm])

  def _reorder(self, new_order):
    self.order = [self.order[new_order[i]] for i in range(len(self.order))]
    for i, id in enumerate(self.order):
      self.refs[id] = i

    self.rows_reordered(None, None, new_order)

  def get_sort_info(self):
    if not self.sort_column_ids: return None, None
    return self.sort_column_ids[0], self.sort_direction
