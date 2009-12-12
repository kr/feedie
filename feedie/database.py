import urlparse
from oauth import oauth
import cgi
import httplib2
from twisted.internet import defer
import urllib
import json
import couchdb

from feedie import http
from feedie import util

debug = False

JSON_PARAMS = 'key startkey endkey'.split()

class ResponseError(Exception):
  pass

def encode_params(params):
  params = params.copy()
  for key in JSON_PARAMS:
    if key in params:
      params[key] = json.dumps(params[key])
  return urllib.urlencode(params)

def classify_error(doc):
  if u'error' in doc and doc[u'error'] == u'conflict':
    return couchdb.client.ResourceConflict(doc)
  return ResponseError(doc)

class AsyncCouch:
  def __init__(self, couchdb, oauth_tokens):
    self.couchdb = couchdb
    uri = urlparse.urlsplit(couchdb.db.resource.uri, 'http')
    self.host = uri.hostname
    self.port = uri.port
    self.base_path = uri.path + '/'
    self.oauth_tokens = oauth_tokens

  def request(self, verb, path, headers, body=None):
    def success(response):
      promise.callback(response)

    promise = util.EventEmitter()

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

    promise = util.EventEmitter()
    verb = verb.upper()
    params = params.copy()
    request_path = self.base_path + path + encode_params(params)
    if debug: print 'COUCH', verb, request_path

    headers = {}
    headers['Accept'] = 'application/json'

    if 'keys' in params:
      body = {'keys': params['keys']}
      del params['keys']

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

  def load_doc(self, doc_id):
    return self.get(urllib.quote_plus(doc_id))

  def save_doc(self, doc):
    def success(result):
      if u'ok' not in result:
        return promise.errback(classify_error(result))
      doc['_id'] = result['id']
      doc['_rev'] = result['rev']
      promise.callback(doc)

    promise = util.EventEmitter()
    doc = doc.copy()

    if '_id' not in doc:
      d = self.post('', body=doc)
    else:
      d = self.put(urllib.quote_plus(doc['_id']), body=doc)

    d.addCallback(success)
    d.addErrback(promise.errback)

    return promise

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
