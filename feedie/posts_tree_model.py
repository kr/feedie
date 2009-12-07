import gtk
import time
import random

from feedie import images

class PostsTreeModel(gtk.GenericTreeModel):
  columns = (
      ('title',      str),
      ('updated_at', str),
      ('star',       gtk.gdk.Pixbuf),
      ('read',       gtk.gdk.Pixbuf),
      ('weight',     int),
  )

  @classmethod
  def colnum(clas, name):
    return [x[0] for x in clas.columns].index(name)

  def __init__(self, feed):
    self.feed = feed
    gtk.GenericTreeModel.__init__(self)
    docs = feed.post_summaries()
    self.docs = dict(((doc['id'], doc) for doc in docs))
    docs = sorted(docs, key=lambda x: x.get('updated_at', 0), reverse=True)

    for doc in docs:
      doc['read'] = random.random() > 0.5

    self.order = [x['id'] for x in docs]
    self.refs = dict(((self.order[i], i) for i in range(len(self.order))))

  def column_title(self, doc):
    return doc.get('title', '(unknown title)')

  def column_updated_at(self, doc):
    return '3:11 p.m.'
    return doc.get('updated_at', '0000-00-00T00:00:00Z')

  def column_read(self, doc):
    return str(doc.get('read', False))
    read = doc.get('read', False)
    return images.get_pixbuf(('blank', 'blank')[read])

  def column_star(self, doc):
    starred = doc.get('starred', False)
    return images.get_pixbuf(('hollow-star', 'star')[starred])

  def column_weight(self, doc):
    return (700, 400)[doc.get('read', False)]

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

