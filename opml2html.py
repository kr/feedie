# opml2html.py - sample code for converting OPML to HTML
from xml.dom.minidom import parse, parseString
import urllib2

#dom1 = parse('mah_links.opml') # parse an XML file by name - uncomment if you want to draw from a file
dom1 = parseString(urllib2.urlopen('http://share.opml.org/opml/top100.opml').read()) #use this to parse a feed

links = dom1.getElementsByTagName('outline')

f = open('links.html','w')

for link in links:
    linktext = '<a href="' + link.getAttribute('htmlUrl') + '">'
    linktext += link.getAttribute('title') + '</a><br />\n'
    print linktext
    f.write(linktext)
    f.flush()

f.close()

