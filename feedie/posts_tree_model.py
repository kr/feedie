import gtk
import time

class PostsTreeModel(gtk.GenericTreeModel):
  column_types = (
      str,
      str,
      str,
      str,
  )

  column_keys = (
      ('updated_at', '0000-00-00T00:00:00Z'),
      ('read', False),
      ('starred', False),
      ('title', '(unknown title)'),
  )

  def __init__(self, feed):
    self.feed = feed
    gtk.GenericTreeModel.__init__(self)
    docs = feed.post_summaries()
    self.docs = dict(((doc['id'], doc) for doc in docs))
    docs = sorted(docs, key=lambda x: x.get('updated_at', 0))
    self.order = [x['id'] for x in docs]
    self.refs = dict(((self.order[i], i) for i in range(len(self.order))))

  def on_get_flags(self):
    return gtk.TREE_MODEL_LIST_ONLY|gtk.TREE_MODEL_ITERS_PERSIST

  def on_get_n_columns(self):
    return len(self.column_types)

  def on_get_column_type(self, index):
    return self.column_types[index]

  def on_get_iter(self, path):
    try:
      return self.order[path[0]]
    except IndexError:
      return None

  def on_get_path(self, rowref):
    return self.refs[rowref]

  def on_get_value(self, rowref, column):
    return str(self.docs[rowref].get(*self.column_keys[column]))

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

