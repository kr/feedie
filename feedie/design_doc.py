import couchdb

DOC_ID = '_design/feedie'

SUMMARY_MAP = '''
function (doc) {
  if (doc.type == 'post') {
    try {
      if (doc.read_updated_at > doc.updated_at) {
        emit(doc.feed_id, {total:1, read:1});
      } else {
        emit(doc.feed_id, {total:1, read:0});
      }
    } catch (e) {
      emit(doc.feed_id, {total:1, read:0});
    }
  }
}
'''

SUMMARY_REDUCE = '''
function (keys, values, rereduce) {
  total = sum(values.map(function (x) x.total));
  read = sum(values.map(function (x) x.read));
  return {total:total, read:read};
}
'''

FEED_MAP = '''
function (doc) {
  if (doc.type == 'feed') {
    try {
      if (!(doc.deleted_at > doc.subscribed_at)) {
        emit(doc._id, doc);
      }
    } catch (e) {
      emit(doc._id, doc);
    }
  }
}
'''

EMIT_SNIPPET = '''
  function emit_snippet(doc) {
    emit(doc.feed_id, {
      _id: doc._id,
      feed_id: doc.feed_id,
      title: doc.title,
      starred: doc.starred,
      read_updated_at: doc.read_updated_at,
      updated_at: doc.updated_at,
    });
  }
'''

FEED_POST_MAP = '''
function (doc) {
  %(EMIT_SNIPPET)s

  if (doc.type == 'post') {
    if (!doc.deleted_at) {
      emit_snippet(doc);
    }
  }
}
''' % locals()

UNREAD_POSTS_MAP = '''
function (doc) {
  %(EMIT_SNIPPET)s

  if (doc.type == 'post') {
    try {
      if (!doc.deleted_at && !(doc.read_updated_at >= doc.updated_at)) {
        emit_snippet(doc);
      }
    } catch (e) {
      emit_snippet(doc);
    }
  }
}
''' % locals()

def view(map, reduce=None):
  d = {'map':map}
  if reduce: d['reduce'] = reduce
  return d

def add_views(db):
  modified = False
  try:
    ddoc = db.couchdb[DOC_ID]
  except couchdb.client.ResourceNotFound:
    ddoc = {'_id': DOC_ID}
    modified = True
  if 'views' not in ddoc:
    ddoc['views'] = {}
  views = ddoc['views']
  if 'summary' not in views:
    views['summary'] = view(SUMMARY_MAP, SUMMARY_REDUCE)
    modified = True
  if 'feed' not in views:
    views['feed'] = view(FEED_MAP)
    modified = True
  if 'feed_post' not in views:
    views['feed_post'] = view(FEED_POST_MAP)
    modified = True
  if 'unread_posts' not in views:
    views['unread_posts'] = view(UNREAD_POSTS_MAP)
    modified = True
  if modified:
    db.couchdb[DOC_ID] = ddoc
