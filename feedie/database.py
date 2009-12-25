import urlparse
from oauth import oauth
import cgi
import httplib2
from twisted.internet import defer
import urllib
try:
  import simplejson as json
except ImportError:
  import json
import couchdb

from feedie import http
from feedie import util

debug = True

JSON_PARAMS = 'key startkey endkey'.split()

class ResponseError(Exception):
  pass

def encode_params(params):
  params = params.copy()
  for key in JSON_PARAMS:
    if key in params:
      params[key] = json.dumps(params[key])
  if not params: return ''
  return '?' + urllib.urlencode(params)

def classify_error(doc):
  if u'error' in doc and doc[u'error'] == u'conflict':
    return couchdb.client.ResourceConflict(doc)
  if u'error' in doc and doc[u'error'] == u'not_found':
    return couchdb.client.ResourceNotFound(doc)
  return ResponseError(doc)

class AsyncCouch:
  def __init__(self, couchdb, oauth_tokens):
    self.couchdb = couchdb
    uri = urlparse.urlsplit(couchdb.resource.uri, 'http')
    self.host = uri.hostname
    self.port = uri.port
    self.base_path = uri.path + '/'
    self.oauth_tokens = oauth_tokens

  def request(self, verb, path, headers, body=None):
    def success(response):
      promise.callback(response)

    promise = defer.Deferred()

    full_http_url = "http://%s:%d%s" % (self.host, self.port, path)
    headers.update(self.make_oauth_headers(verb, full_http_url))
    client = http.Client(self.host, self.port)
    d = client.request(verb, path, headers=headers, body=body)
    d.addCallback(success)
    d.addErrback(promise.errback)
    return promise

  def interact(self, verb, path, success_status, params, body=None):
    def success(response):
      if debug: print 'COMPLETE', verb, request_path
      value = json.loads(response.body)
      if response.status.code == success_status:
        promise.callback(value)
      else:
        promise.errback(classify_error(value))

    promise = defer.Deferred()
    verb = verb.upper()
    params = params.copy()
    request_path = self.base_path + path + encode_params(params)
    if debug: print 'COUCH', verb, request_path

    headers = {}
    headers['Accept'] = 'application/json'

    if body:
      request = self.request(verb, request_path, headers, body=json.dumps(body))
    else:
      request = self.request(verb, request_path, headers)

    request.addCallback(success)
    request.addErrback(promise.errback)

    return promise

  def get(self, path, success_status=200, **params):
    return self.interact('GET', path, success_status, params)

  def post(self, path, success_status=201, body=None, **params):
    return self.interact('POST', path, success_status, params, body=body)

  def put(self, path, success_status=201, body=None, **params):
    return self.interact('PUT', path, success_status, params, body=body)

  @defer.inlineCallbacks
  def view(self, name, **params):
    if '/' in name:
      design_doc_name, view_name = name.split('/')
      path = '_design/%s/_view/%s' % (urllib.quote_plus(design_doc_name),
                                      urllib.quote_plus(view_name))
    else:
      path = name
    if 'keys' in params:
      keys = params.pop('keys')
      body = {'keys': keys}
      response = yield self.post(path, success_status=200, body=body, **params)
    else:
      response = yield self.get(path, **params)
    defer.returnValue(response['rows'])

  def load_doc(self, doc_id):
    return self.get(urllib.quote_plus(doc_id))

  def save_doc(self, doc):
    def success(result):
      if u'ok' not in result:
        return promise.errback(classify_error(result))
      doc['_id'] = result['id']
      doc['_rev'] = result['rev']
      promise.callback(doc)

    promise = defer.Deferred()
    doc = doc.copy()

    if '_id' not in doc:
      d = self.post('', body=doc)
    else:
      d = self.put(urllib.quote_plus(doc['_id']), body=doc)

    d.addCallback(success)
    d.addErrback(promise.errback)

    return promise

  @defer.inlineCallbacks
  def get_attachment(self, doc_id, name):
    path = '%s/%s' % (doc_id, name)
    request_path = self.base_path + path
    response = yield self.request('GET', request_path, {})
    if (not response.status) or response.status.code == 200:
      defer.returnValue(response.body)
    if not response.body:
      raise couchdb.client.ResourceNotFound({})
    value = json.loads(response.body)
    raise classify_error(value)

  @defer.inlineCallbacks
  def put_attachment(self, doc_id, name, data, rev):
    path = '%s/%s' % (doc_id, name)
    request_path = self.base_path + path + encode_params(dict(rev=rev))
    yield self.request('PUT', request_path, {}, data)

  @defer.inlineCallbacks
  def delete_attachment(self, doc_id, name, rev):
    path = '%s/%s' % (doc_id, name)
    request_path = self.base_path + path + encode_params(dict(rev=rev))
    yield self.request('DELETE', request_path, {})

  # returns a list of documents (maybe with fewer than doc_ids)
  @defer.inlineCallbacks
  def load_docs(self, doc_ids):
    rows = yield self.view('_all_docs', include_docs='true', keys=doc_ids)
    defer.returnValue([row['doc'] for row in rows])

  # returns a list of responses as documented in
  # http://wiki.apache.org/couchdb/HTTP_Bulk_Document_API
  def save_docs(self, docs):
    return self.post('_bulk_docs', body=dict(docs=docs))

  @defer.inlineCallbacks
  def modify_doc(self, doc_id, f, load_first=False, doc=None):
    while True:
      if doc is None:
        if load_first:
          doc = yield self.load_doc(doc_id)
        else:
          doc = {'_id': doc_id}

      f(doc)

      try:
        doc = yield self.save_doc(doc)
        defer.returnValue(doc)
      except couchdb.client.ResourceConflict:
        load_first, doc = True, None

  # f may signal that it doesn't want to modify a doc by removing all entries
  # from the document.
  # TODO: return a list of promises, not just one
  @defer.inlineCallbacks
  def modify_docs(self, doc_ids, f, load_first=False, docs=None):
    if docs is None:
      if load_first:
        docs = yield self.load_docs(doc_ids)
      else:
        docs = [{'_id': doc_id} for doc_id in doc_ids]

    for doc in docs:
      f(doc)

    docs = filter(None, docs) # leave out ones they don't want to modify

    rev = dict([(doc['_id'], doc) for doc in docs])

    rows = yield self.save_docs(docs)
    conflict_ids = []
    successes = {}
    for row in rows:
      if 'error' in row:
        if row['error'] == 'conflict':
          conflict_ids.append(row['id'])
        else:
          raise classify_error(row)
      else:
        doc = rev[row['id']]
        doc['_id'] = row['id']
        doc['_rev'] = row['rev']
        successes[row['id']] = doc

    if conflict_ids:
      inner_docs = yield self.modify_docs(conflict_ids, f, True)
      for inner_doc in inner_docs:
        successes[inner_doc['_id']] = inner_doc

    defer.returnValue([successes[id] for id in doc_ids if id in successes])

  def make_oauth_headers(self, verb, full_http_url):
    consumer = oauth.OAuthConsumer(self.oauth_tokens['consumer_key'],
        self.oauth_tokens['consumer_secret'])
    access_token = oauth.OAuthToken(self.oauth_tokens['token'],
        self.oauth_tokens['token_secret'])
    sig_method = oauth.OAuthSignatureMethod_HMAC_SHA1
    query = urlparse.urlsplit(full_http_url).query
    querystr_as_dict = dict(cgi.parse_qsl(query))
    req = oauth.OAuthRequest.from_consumer_and_token(consumer, access_token,
        http_method = verb,
        http_url = full_http_url,
        parameters = querystr_as_dict)
    req.sign_request(sig_method(), consumer, access_token)
    return httplib2._normalize_headers(req.to_header())
