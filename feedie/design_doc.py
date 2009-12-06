import couchdb

from feedie import conn

DOC_ID = '_design/feedie'
VERSION = 1 # change this when you modify the design doc

SUMMARY_MAP = '''
function (doc) {
  if (doc.type == 'post') {
    try {
      if (doc.read_at > doc.updated_at) {
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
    if (!doc.deleted_at) {
      emit(doc._id, doc);
    }
  }
}
'''

FEED_POST_MAP = '''
function (doc) {
  if (doc.type == 'post') {
    if (!doc.deleted_at) {
      var info = {
        id: doc._id,
        feed_id: doc.feed_id,
        title: doc.title,
        starred: doc.starred,
        read: doc.read,
        updated_at: doc.updated_at,
      };
      emit(['feed', 0, doc.feed_id], info);
    }
  }
}
'''

def view(map, reduce=None):
  d = {'map':map}
  if reduce: d['reduce'] = reduce
  return d

def add_views():
  db = conn.database.db # raw couchdb
  modified = False
  try:
    ddoc = db[DOC_ID]
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
  if modified:
    db[DOC_ID] = ddoc
