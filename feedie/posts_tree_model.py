import gtk
import time
import gobject
from twisted.internet import reactor, defer

from feedie import images

class PostsTreeModel(gtk.GenericTreeModel):
  columns = (
      ('title',       str),
      ('age',         int),
      ('pretty_date', str),
      ('star',        gtk.gdk.Pixbuf),
      ('read',        gtk.gdk.Pixbuf),
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

  def insert_doc(self, doc):
    id = doc._id
    if id in self.docs: return
    n = len(self.order)
    self.order.append(id)
    self.docs[id] = doc
    self.refs[id] = n
    self.row_inserted(n, self.get_iter(n))
    doc.connect('changed', self.post_changed)

  def post_changed(self, post, event_name, field_name=None):
    n = self.on_get_path(post._id)
    self.row_changed(n, self.get_iter(n))

  def post_added(self, feed, event_name, post):
    self.insert_doc(post)

  def post_removed(self, *args):
    print 'post removed', args

  @defer.inlineCallbacks
  def load(self):
    posts = yield self.feed.post_summaries()
    for post in posts:
      self.insert_doc(post)

  def column_title(self, doc):
    return doc.title

  def column_pretty_date(self, doc):
    now = time.time()
    year = time.gmtime(now).tm_year
    t = time.gmtime(doc.updated_at)
    if t.tm_year != year:
      return time.strftime('%d %b %Y', t)
    if abs(now - doc.updated_at) > 82800: # 23 Hours
      return time.strftime('%d %b', t)
    return time.strftime('%I:%M %p', t)

  def column_age(self, doc):
    return -doc.updated_at

  def column_read(self, doc):
    read = doc.read
    return images.get_pixbuf(('dot', 'blank')[read])

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

  def on_get_value(self, rowref, column):
    doc = self.docs[rowref]
    colname, type = self.columns[column]

    return getattr(self, 'column_' + colname)(doc)

  def on_iter_next(self, rowref):
    try:
      return self.order[self.refs[rowref] + 1]
    except IndexError:
      return None

  def on_iter_children(self, parent):
    if parent: return None
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

