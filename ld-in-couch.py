#!/usr/bin/python

""" 
  Enables you to store, process and query RDF-based Linked Data in Apache CouchDB.

@author: Michael Hausenblas, http://mhausenblas.info/#i
@since: 2012-10-06
@status: init
"""

import os
import sys
import logging
import getopt
import string
import StringIO
import urlparse
import urllib
import urllib2
import string
import cgi
import time
import datetime
import json
import io
from BaseHTTPServer import BaseHTTPRequestHandler
from os import curdir, sep
from couchdbkit import Server, Database, Document, StringProperty, DateTimeProperty, StringListProperty
from restkit import BasicAuth, set_logging

# Configuration, change as you see fit
DEBUG = True
PORT = 7172
COUCHDB_SERVER = 'http://127.0.0.1:5984/'
COUCHDB_DB = 'rdf'
COUCHDB_USERNAME = 'admin'
COUCHDB_PASSWORD = 'admin'

# CouchDB views, don't touch unless you know what you're doing
LOOKUP_BY_SUBJECT_PATH = 'rdf/_design/lookup/_view/by_subject?key='

if DEBUG:
	FORMAT = '%(asctime)-0s %(levelname)s %(message)s [at line %(lineno)d]'
	logging.basicConfig(level=logging.DEBUG, format=FORMAT, datefmt='%Y-%m-%dT%I:%M:%S')
else:
	FORMAT = '%(asctime)-0s %(message)s'
	logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt='%Y-%m-%dT%I:%M:%S')

# The main LD-in-Couch service
class LDInCouchServer(BaseHTTPRequestHandler):

	# changes the default behavour of logging everything - only in DEBUG mode
	def log_message(self, format, *args):
		if DEBUG:
			try:
				BaseHTTPRequestHandler.log_message(self, format, *args)
			except IOError:
				pass
		else:
			return
	
	# reacts to GET request by serving static content in standalone mode as well as
	# handles API calls for managing content
	def do_GET(self):
		parsed_path = urlparse.urlparse(self.path)
		target_url = parsed_path.path[1:]
		
		# API calls
		if self.path.startswith('/q/'):
			self.send_error(404,'File Not Found: %s' % self.path) #self.serve_lookup(self.path.split('/')[-1])
		# static stuff (for standalone mode - typically served by Apache or nginx)
		elif self.path == '/':
			self.serve_content('index.html')
		elif self.path.endswith('.ico'):
			self.serve_content(target_url, media_type='image/x-icon')
		elif self.path.endswith('.html'):
			self.serve_content(target_url, media_type='text/html')
		elif self.path.endswith('.js'):
			self.serve_content(target_url, media_type='application/javascript')
		elif self.path.endswith('.css'):
			self.serve_content(target_url, media_type='text/css')
		elif self.path.startswith('/img/'):
			if self.path.endswith('.gif'):
				self.serve_content(target_url, media_type='image/gif')
			elif self.path.endswith('.png'):
				self.serve_content(target_url, media_type='image/png')
			else:
				self.send_error(404,'File Not Found: %s' % target_url)
		else:
			self.send_error(404,'File Not Found: %s' % target_url)
		return
	
	# look up an entity
	def serve_lookup(self, entryid):
		pass
		# try:
		# 	backend = 
		# 	(entry_found, entry) = backend.find(entryid)
		# 	
		# 	if entry_found:
		# 		self.send_response(200)
		# 		self.send_header('Content-type', 'application/json')
		# 		self.end_headers()
		# 		self.wfile.write(json.dumps(entry))
		# 	else:
		# 		self.send_error(404,'Entry with ID %s not found.' %entryid)
		# 	return
		# except IOError:
		# 	self.send_error(404,'Entry with ID %s not found.' %entryid)	
	
	# serves static content from file system
	def serve_content(self, p, media_type='text/html'):
		try:
			f = open(curdir + sep + p)
			self.send_response(200)
			self.send_header('Content-type', media_type)
			self.end_headers()
			self.wfile.write(f.read())
			f.close()
			return
		except IOError:
			self.send_error(404,'File Not Found: %s' % self.path)
	
	# serves remote content via forwarding the request
	def serve_URL(self, remote_url, media_type='application/json'):
		logging.debug('REMOTE GET %s' %remote_url)
		self.send_response(200)
		self.send_header('Content-type', media_type)
		self.end_headers()
		data = urllib.urlopen(remote_url)
		self.wfile.write(data.read())
	

# A single entity, expressed in RDF data model
class RDFEntity(Document):
	g = StringProperty() # the graph this entity belongs to
	s = StringProperty() # the one and only subject
	p = StringListProperty() # list of predicates
	o = StringListProperty() # list of objects
	o_in = StringListProperty() # list of back-links (read: 'object in')

# The Apache CouchDB backend for LD-in-Couch
class LDInCouchBinBackend(object):
	
	# init with URL of CouchDB server, database name, and credentials
	def __init__(self, serverURL, dbname, username, pwd):
		self.serverURL = serverURL
		self.dbname = dbname
		self.username = username
		self.pwd = pwd
		self.server = Server(self.serverURL, filters=[BasicAuth(self.username, self.pwd)])
		set_logging('info') # suppress DEBUG output of the couchdbkit/restkit
	
	# looks up a document via its ID 
	def look_up_by_id(self, eid):
		try:
			db = self.server.get_or_create_db(self.dbname)
			if db.doc_exist(eid):
				ret = db.get(eid)
				return (True, ret)
			else:
				return (False, None)
		except Exception as err:
			logging.error('Error while looking up entity: %s' %err)
			return (False, None)
	
	# finds an RDFEntity document by subject and returns its ID, for example:
	# curl 'http://127.0.0.1:5984/rdf/_design/lookup/_view/by_subject?key="http%3A//example.org/%23r"'
	def look_up_by_subject(self, subject, in_graph):
		viewURL = ''.join([COUCHDB_SERVER, LOOKUP_BY_SUBJECT_PATH, '"', urllib.quote(subject), urllib.quote(in_graph), '"'])
		logging.debug(' ... querying view %s ' %(viewURL))
		doc = urllib.urlopen(viewURL)
		doc = json.JSONDecoder().decode(doc.read())
		if len(doc['rows']) > 0:
			eid = doc['rows'][0]['id']
			logging.debug('Entity with %s in subject position (in graph %s) has the ID %s' %(subject, in_graph, eid))
			return eid
		else:
			logging.debug('Entity with %s in subject position does not exist, yet in graph %s' %(subject, in_graph))
			return None
	
	
	# imports an RDF NTriples file triple by triple into JSON documents of RDFEntity type
	# as of the pseudo-algorthim laid out in https://github.com/mhausenblas/ld-in-couch/blob/master/README.md
	def import_NTriples(self, file_name, target_graph):
		triple_count = 1
		subjects = [] # for remembering which subjects we've already seen
		logging.info('Starting import ...')
		input_doc = open(file_name, "r")
		db = self.server.get_or_create_db(self.dbname)
		RDFEntity.set_db(db) # associate the document type with database
		
		if(not target_graph):
			target_graph = file_name
		
		logging.info('Importing NTriples file \'%s\' into graph <%s>' %(file_name, target_graph))
			
		# scan each line (triple) of the input document
		for input_line in input_doc:
			 # parsing a triple @@FIXME: employ real NTriples parser here!
			triple = input_line.split(' ') # naively assumes SPO is separated by a single whitespace
			is_literal_object = False
			s = triple[0][1:-1] # get rid of the <>, naively assumes no bNodes for now
			p = triple[1][1:-1] # get rid of the <>
			o = triple[2][1:-1] # get rid of the <> or "", naively assumes no bNodes for now
			if not triple[2][0] == '<':
				is_literal_object = True
			logging.debug('-'*20)
			logging.debug('#%d: S: %s P: %s O: %s' %(triple_count, s, p, o))
			
			# creating RDFEntity as we need
			if not s in subjects: # a new resource, never seen in subject position before ...
				logging.debug('%s is a resource I haven\'t seen in subject position, yet' %(s))
				subjects.append(s)
				try:
					doc = RDFEntity(g=target_graph, s=s,  p=[p], o=[o], o_in=[]) # ... so create a new entity doc
					doc.save()
					eid = doc['_id']
					logging.debug(' ... created new entity with ID %s' %eid)
				except Exception as err:
					logging.error('ERROR while creating entity: %s' %err)
			else: # we've already seen the resource in subject position ...
				logging.debug('I\'ve seen %s already in subject position' %(s))
				eid = self.look_up_by_subject(s, target_graph)  # ... so look up existing entity doc by subject ...
				try:
					doc = db.get(eid)  # ... and update entity doc with new PO pair
					doc['p'].append(p)
					doc['o'].append(o)
					db.save_doc(doc)
					logging.debug(' ... updated existing entity with ID %s' %eid)
				except Exception as err:
					logging.error('ERROR while updating existing entity: %s' %err)
			
			# setting back-links for non-literals in object position
			if not is_literal_object: # make sure to remember non-literal objects via back-link
				ref_eid = self.look_up_by_subject(o, target_graph)  # ... check if already exists ...
				
				if ref_eid:
					try:
						doc = db.get(ref_eid)  # ... and update entity doc back-link
						doc['o_in'].append(eid)
						db.save_doc(doc)
						logging.debug(' ... updated existing entity with ID %s with back-link %s' %(ref_eid, eid))
					except Exception as err:
						logging.error('ERROR while updating existing entity: %s' %err)
				else:
					subjects.append(o) # need to remember that we've now seen this object value already in subject position
					try:
						doc = RDFEntity(g=target_graph, s=o,  p=[], o=[], o_in =[eid]) # ... or create a new back-link entity doc
						doc.save()
						logging.debug(' ... created new back-link entity with ID %s with back-link %s' %(doc['_id'], eid))
					except Exception as err:
						logging.error('ERROR while creating back-link entity: %s' %err)
			
			triple_count += 1
			
		logging.info('Import completed. I\'ve processed %d triples and seen %d subjects (incl. back-links).' %(triple_count, len(subjects)))
	
def usage():
	print('Usage: python ld-in-couch.py -c $couchdbserverURL -u $couchdbUser -p $couchdbPwd')
	print('To import an RDF NTriples document (can specify target graph with -g if you want to):')
	print(' python ld-in-couch.py -i data/example_0.nt')
	print('To run the service (note: these are all defaults, so don\'t need to specify them):')
	print(' python ld-in-couch.py -c http://127.0.0.1:5984/ -u admin -p admin')

if __name__ == '__main__':
	do_import = False
	target_graph = ''
	try:
		# extract and validate options and their arguments
		logging.info('-'*80)
		logging.info('*** CONFIGURATION ***')
		opts, args = getopt.getopt(sys.argv[1:], 'hi:g:c:u:p:', ['help', 'import=', 'graph=', 'couchdbserver=', 'username=', 'password='])
		for opt, arg in opts:
			if opt in ('-h', '--help'):
				usage()
				sys.exit()
			elif opt in ('-i', '--import'):
				input_file = os.path.abspath(arg)
				do_import = True
			elif opt in ('-g', '--graph'):
				target_graph = arg
			elif opt in ('-c', '--couchdbserver'):
				couchdbserver = arg
				logging.info('Using CouchDB server: %s' %couchdbserver)
			elif opt in ('-u', '--username'):
				couchdbusername = arg
				logging.info('Using CouchDB username: %s' %couchdbusername)
			elif opt in ('-p', '--password'): 
				couchdbpassword = arg
				logging.info('Using CouchDB password: %s' %couchdbpassword)
		logging.info('-'*80)
		
		if do_import:
			backend = LDInCouchBinBackend(serverURL = COUCHDB_SERVER , dbname = COUCHDB_DB, username = COUCHDB_USERNAME, pwd = COUCHDB_PASSWORD)
			backend.import_NTriples(input_file, target_graph)
		else:
			from BaseHTTPServer import HTTPServer
			server = HTTPServer(('', PORT), LDInCouchServer)
			logging.info('LDInCouchServer started listening on port %s, use {Ctrl+C} to shut-down ...' %PORT)
			server.serve_forever()
	except getopt.GetoptError, err:
		print str(err)
		usage()
		sys.exit(2)