import couchdb

DOC_ID = '_design/feedie'

SUMMARY_MAP = '''
function (doc) {
  if (doc.type == 'post' && !doc.deleted_at) {
    var summary = {total:1,read:0,starred_total:0,starred_read:0};
    try {

      if (doc.read_updated_at >= doc.updated_at) {
        summary.read = 1;
      }

      if (!doc.deleted_at && doc.starred) {
        summary.starred_total = 1;
        if (doc.read_updated_at >= doc.updated_at) {
          summary.starred_read = 1;
        }
      }

      emit(doc.feed_id, summary);
    } catch (e) {
      emit(doc.feed_id, summary);
    }
  }
}
'''

SUMMARY_REDUCE = '''
function (keys, values, rereduce) {
  total = sum(values.map(function (x) x.total));
  read = sum(values.map(function (x) x.read));
  starred_total = sum(values.map(function (x) x.starred_total));
  starred_read = sum(values.map(function (x) x.starred_read));
  return {
    total:total,
    read:read,
    starred_total:starred_total,
    starred_read:starred_read,
  };
}
'''

FEED_MAP = '''
function (doc) {
  if (doc.type == 'feed') {
    emit(doc._id, doc);
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

  if (doc.type == 'post' && !doc.deleted_at) {
    emit_snippet(doc);
  }
}
''' % locals()

UNREAD_POSTS_MAP = '''
function (doc) {
  %(EMIT_SNIPPET)s

  if (doc.type == 'post' && !doc.deleted_at) {
    try {
      if (!(doc.read_updated_at >= doc.updated_at)) {
        emit_snippet(doc);
      }
    } catch (e) {
      emit_snippet(doc);
    }
  }
}
''' % locals()

STARRED_POSTS_MAP = '''
function (doc) {
  %(EMIT_SNIPPET)s

  if (doc.type == 'post' && !doc.deleted_at) {
    try {
      if (doc.starred) {
        emit_snippet(doc);
      }
    } catch (e) {
      emit_snippet(doc);
    }
  }
}
''' % locals()

POSTS_TO_GC = '''
function (doc) {
  if (doc.type != 'post') return;
  if (doc.starred) return;

  if (doc.feed_deleted) {
    emit(doc._id, doc._rev);
    return;
  }

  if (doc.deleted_at) return;
  if (doc.read_updated_at >= doc.updated_at) {
    emit(doc._id, doc._rev);
  }
}
'''

DELETED_FEEDS = '''
function (doc) {
  if (doc.type != 'feed') return;
  if (doc.deleted_at > doc.subscribed_at) {
    emit(doc._id, {
      _rev: doc._rev,
      subscribed_at: doc.subscribed_at,
    });
  }
}
'''

REDIRECTED_FEEDS = '''
function (doc) {
  if (doc.type != 'feed') return;
  if (doc.error == 'redirect') {
    emit(doc._id, {
      _rev: doc._rev,
      subscribed_at: doc.subscribed_at,
    });
  }
}
'''

POSTS_TO_MARK_FEED_IS_DELETED = '''
function (doc) {
  if (doc.type != 'post') return;
  emit(doc.feed_id, {post_id: doc._id, post_rev: doc._rev});
}
'''

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
  if 'starred_posts' not in views:
    views['starred_posts'] = view(STARRED_POSTS_MAP)
    modified = True
  if 'posts_to_gc' not in views:
    views['posts_to_gc'] = view(POSTS_TO_GC)
    modified = True
  if 'deleted_feeds' not in views:
    views['deleted_feeds'] = view(DELETED_FEEDS)
    modified = True
  if 'redirected_feeds' not in views:
    views['redirected_feeds'] = view(REDIRECTED_FEEDS)
    modified = True
  if 'posts_to_mark_feed_is_deleted' not in views:
    views['posts_to_mark_feed_is_deleted'] = view(POSTS_TO_MARK_FEED_IS_DELETED)
    modified = True
  if modified:
    db.couchdb[DOC_ID] = ddoc
