# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
# 
# The contents of this file are subject to the Mozilla Public License
# Version 1.1 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
# 
# Software distributed under the License is distributed on an "AS IS"
# basis, WITHOUT WARRANTY OF ANY KIND, either express or implied. See the
# License for the specific language governing rights and limitations
# under the License.
# 
# The Original Code is Komodo code.
# 
# The Initial Developer of the Original Code is ActiveState Software Inc.
# Portions created by ActiveState Software Inc are Copyright (C) 2000-2007
# ActiveState Software Inc. All Rights Reserved.
# 
# Contributor(s):
#   ActiveState Software Inc
# 
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
# 
# ***** END LICENSE BLOCK *****

# DOM - Prefs interface code.
# this is used both in the implementation of the preferences system (koPrefs.py) as well
# as by code that wishes to parse files and then have them turned into preferences.

from xml.dom import minidom
from xml.sax import SAXParseException
from xpcom import components, ServerException, COMException, nsError
from xpcom.server.enumerator import SimpleEnumerator
from xpcom.server import WrapObject, UnwrapObject
from xpcom.client import WeakReference
import re, sys, os, cgi
from eollib import newl
import logging
import shutil
import timeline
import uriparse

log = logging.getLogger('koXMLPrefs')
#log.setLevel(logging.DEBUG)

_timers = {} # used for timeline stuff

# convert a string containing 0, 1, True, False
def _convert_boolean(value):
    try:
        return int(value)
    except:
        return value.lower() == "true"

def SmallestVersionFirst(a, b):
    """Compare two version strings and return:
        -1 if a < b
         0 if a == b
        +1 if a > b
    """
    return cmp([int(elem) for elem in a.split('.')],
               [int(elem) for elem in b.split('.')])


def pickleCache(object, filename):
    """
    Pickle a pref object to a pref pickle file given the pref's
    ordinary XML file name.
    """
    from tempfile import mkstemp
    (fdes, pickleFilename) = mkstemp(".tmp", "koPickle_")
    import cPickle
    file = os.fdopen(fdes, "wb")
    try:
        try:
            log.debug("Pickling object %s to %r", object, pickleFilename)
            cPickle.dump(object, file, 1)
            log.info("saved the pickle to %r", pickleFilename)
        except:
            log.exception("pickleCache error for file %r", pickleFilename)
            try:
                file.close()
                file = None
                os.unlink(pickleFilename)
            except IOError, details:
                log.error("Could not erase the incomplete pickle file %r: %s",
                          pickleFilename, details)
    finally:
        if file is not None:
            file.close()
            # Avoid copying bytes when writing to a profile file,
            # although this is hard to do on Windows
            import shutil
            shutil.move(pickleFilename, filename)

def pickleCacheOKToLoad(xml_filename):
    """
    Determines if there is a cached filename valid to use inplace of
    the passed XML filename.
    
    Returns the filename IF AND ONLY IF the pref's pickle file is OLDER
    than the pref's XML file.
    
    Return None otherwise.
    """
    pickleFilename = "%s%sc" % os.path.splitext(xml_filename)

    # Determine whether the pickle file is newer than (or the same age as)
    # the XML file.
    try:
        (mode,ino,dev,nlink,uid,gid,size,atime,mtime,ctime) = os.stat(xml_filename)
        normal_mtime = mtime
    except:
        log.debug("pickleCacheOKToLoad: Can't stat file %r", xml_filename)
        normal_mtime = None

    try:
        (mode,ino,dev,nlink,uid,gid,size,atime,mtime,ctime) = os.stat(pickleFilename)
        pickle_mtime = mtime
    except:
        log.debug("pickleCacheOKToLoad: Can't stat pickle file %r", pickleFilename)
        return None

    if normal_mtime is not None and pickle_mtime < normal_mtime:
        return None

    return pickleFilename

    
def dePickleCache(pickleFilename):
    """
    Return a pref object from a pref pickle file.
    Assumes that pickleCacheOKToLoad() has been called
    """
    import cPickle
    try:
        file = open(pickleFilename, "rb")
    except IOError:
        log.warn("dePickleCache: Can't open file %r", pickleFilename)
        return None

    try:
        try:
            log.info("Loading preferences from pickle %r", pickleFilename)
            return cPickle.load(file)
        except:
            log.exception("dePickleCache: Couldn't depickle %r", pickleFilename)
            
    finally:
        file.close()

def writeXMLHeader(stream):
    # Put in some XML boilerplate.
    stream.write('<?xml version="1.0"?>%s' % newl)
    stream.write('<!-- Komodo Preferences File - DO NOT EDIT -->%s%s' % (newl, newl));

def writeXMLFooter(stream):
    pass

# This could well be in an IDL file - but there is no clear way
# to register such global preferences - so we just
# define and register them here.
class koGlobalPreferenceDefinition:
    SAVE_DEFAULT = 0 # Save XML and cached fast version.
    SAVE_XML_ONLY = 1 # Save only the XML version.
    SAVE_FAST_ONLY = 2 # Save only fast cache version.
    def __init__(self, **kw):
        self.name = None
        self.user_filename = None
        self.shared_filename = None
        self.defaults_filename = None
        self.save_format = self.SAVE_DEFAULT
        self.contract_id = None
        for name, val in kw.items():
            if not self.__dict__.has_key(name):
                raise ValueError, "Unknown keyword param '%s'" % (name,)
            self.__dict__[name] = val

def _dispatch_deserializer(ds, node, parentPref, prefFactory, basedir=None, chainNotifications=0):
    """Find out which deserializer function should
    handle deserializing a particular node."""
    
    # Have to convert dsfunname from unicode to
    # ascii in order to use apply().
    dsfunname = u"_ds_" + node.nodeName
    if hasattr(ds, dsfunname):
        getattr(ds, dsfunname)(node, parentPref, basedir)
    else:
        pref = prefFactory.deserializeNode(node, parentPref, basedir, chainNotifications)
        return pref

class koPreferenceSetDeserializer:
    """
    Creates preference sets from minidom nodes.
    """
    def DOMDeserialize(self, rootElement, parentPref, prefFactory, basedir=None, chainNotifications=0):
        """We know how to deserialize preferent-set elements."""
        timeline.startTimer('koPreferenceSet instance creation')
        # Create a new preference set and rig it into the preference set hierarchy.
        xpPrefSet = components.classes["@activestate.com/koPreferenceSet;1"] \
                  .createInstance(components.interfaces.koIPreferenceSet)
        newPrefSet = UnwrapObject(xpPrefSet)
        newPrefSet.chainNotifications = chainNotifications
        timeline.stopTimer('koPreferenceSet instance creation')
        try:
            newPrefSet.id = rootElement.getAttribute('id') or ""
        except KeyError:
            newPrefSet.id = ""
        try:
            newPrefSet.idref = rootElement.getAttribute('idref') or ""
        except KeyError:
            newPrefSet.idref = ""

        # Iterate over the elements of the preference set,
        # deserializing them and fleshing out the new preference
        # set with content.
        childNodes = rootElement.childNodes

        for node in childNodes:
            if node and node.nodeType == minidom.Node.ELEMENT_NODE:
                timeline.startTimer('_dispatch_deserializer')
                if node.hasAttribute('validate'):
                    newPrefSet.setValidation(node.getAttribute('id'), node.getAttribute('validate'))
                pref = _dispatch_deserializer(self, node, newPrefSet, prefFactory, basedir, chainNotifications)
                timeline.stopTimer('_dispatch_deserializer')
                if pref:
                    if pref.id:
                        timeline.startTimer('setPref')
                        newPrefSet.setPref(pref.id, pref)
                        timeline.stopTimer('setPref')
                    else:
                        log.error("Preference has no id - dumping preference:")
                        pref.dump(0)

        return xpPrefSet 

    def _ds_helper_get_child_text(self, node):
        if node.hasChildNodes():
            return getChildText(node)
        elif node.hasAttribute('relative'):
            return ""
        else:
            return None

    def _ds_helper(self, node, insertFunction, convertFunction, basedir=None):
        childtext = self._ds_helper_get_child_text(node)
        if childtext is None:
            # For strings we insert the empty string.  However, for
            # other types it implies something bad, but we shouldn't
            # fail totally!
            if node.nodeName == "string":
                try:
                    insertFunction(node.getAttribute('id'),
                                   convertFunction(''))
                except KeyError:
                    insertFunction("", convertFunction(""))
            else:
                log.debug("Node '%s' is empty - pretending it doesnt exist!",
                          node)
        else:
            if basedir and node.nodeName == "string" and node.getAttribute('relative'):
                childtext = uriparse.UnRelativize(basedir, childtext, node.getAttribute('relative'))
            if childtext:
                insertFunction(node.getAttribute('id'),
                               convertFunction(childtext))

    def _ds_string(self, node, prefSet, basedir=None):
        self._ds_helper(node, prefSet.setStringPref, unicode, basedir)

    def _ds_long(self, node, prefSet, basedir=None):
        self._ds_helper(node, prefSet.setLongPref, int, basedir)

    def _ds_double(self, node, prefSet, basedir=None):
        self._ds_helper(node, prefSet.setDoublePref, float, basedir)

    def _ds_boolean(self, node, prefSet, basedir=None):
        self._ds_helper(node, prefSet.setBooleanPref, _convert_boolean, basedir)

class koOrderedPreferenceDeserializer:
    def DOMDeserialize(self, rootElement, parentPref, prefFactory, basedir=None, chainNotifications=0):
        """We know how to deserialize ordered-preference elements."""

        # Create a new ordered preference.
        xpOrderedPref = components.classes["@activestate.com/koOrderedPreference;1"] \
                  .createInstance(components.interfaces.koIOrderedPreference)
        newOrderedPref = UnwrapObject(xpOrderedPref)
        try:
            newOrderedPref.id = rootElement.getAttribute("id") or ""
        except KeyError:
            newOrderedPref.id = ""

        # Iterate over the elements of the preference set,
        # deserializing them and fleshing out the new preference
        # set with content.
        childNodes = rootElement.childNodes

        for childNode in childNodes:
            if childNode and childNode.nodeType == minidom.Node.ELEMENT_NODE:
                pref = _dispatch_deserializer(self, childNode, newOrderedPref, prefFactory, basedir)
                if pref:
                    newOrderedPref.appendPref(pref)

        return xpOrderedPref 

    def _ds_helper(self, node, insertFunction, convertFunction, basedir=None):
        childtext = getChildText(node)
        if basedir and node.nodeName == "string" and node.getAttribute('relative'):
            childtext = uriparse.UnRelativize(basedir, childtext, node.getAttribute('relative'))
        insertFunction(convertFunction(childtext))

    def _ds_string(self, node, orderedPref, basedir=None):
        self._ds_helper(node, orderedPref.appendStringPref, unicode)

    def _ds_long(self, node, orderedPref, basedir=None):
        self._ds_helper(node, orderedPref.appendLongPref, int)

    def _ds_double(self, node, orderedPref, basedir=None):
        self._ds_helper(node, orderedPref.appendDoublePref, float)

    def _ds_boolean(self, node, orderedPref, basedir=None):
        self._ds_helper(node, orderedPref.appendBooleanPref, _convert_boolean)

_encre = re.compile('([^\x00-\x7f])')
def _makeCharRef(m):
    # replace with XML decimal char entity, e.g. '&#7;'
    return '&#%d;' % ord(m.group(1))
def _xmlencode(s):
    """ Taken from codeintel2/parseutil.py """
    return _encre.sub(_makeCharRef, cgi.escape(s))
 
def serializePref(stream, pref, prefType, prefName=None, basedir=None):
    """Serialize one preference to a stream as appropriate for its type.
    Some preferences, e.g. those in ordered preferences, may not have names.
    """
    #print "Serialzing: '%s', with type '%s', value '%s'" % (prefName, prefType, pref )
    if prefType == "string":
        attrs = {}
        if prefName:
            attrs['id'] = cgi.escape(prefName,1)
        # serialize string prefs as UTF-8
        if basedir:
            try:
                relative = uriparse.RelativizeURL(basedir, pref)
                if relative != pref:
                    if pref.find("://") > -1:
                        attrs['relative']='url'
                    else:
                        attrs['relative']='path'
                    pref = relative
            except Exception, e:
                # XXX quick fix bug 65913
                log.exception(e)
                pass # pass and use original value
        pref = cgi.escape(pref)
        data = u'  <string'
        for a,v in attrs.items():
            data += ' %s="%s"' % (a,v)
        data += u'>%s</string>%s' % (_xmlencode(pref), newl)
        data = data.encode("utf-8")
        stream.write(data)
    elif prefType in ("boolean"):
        if prefName is None:
            stream.write('  <%s>%d</%s>%s' % (prefType, pref,
                                              prefType, newl))
        else:
            stream.write('  <%s id="%s">%d</%s>%s'\
                         % (prefType, cgi.escape(prefName,1),
                            pref, prefType, newl))
    elif prefType in ("long", "double"):
        if prefName is None:
            stream.write('  <%s>%s</%s>%s' % (prefType, cgi.escape(str(pref)),
                                              prefType, newl))
        else:
            stream.write('  <%s id="%s">%s</%s>%s'\
                         % (prefType, cgi.escape(prefName,1),
                            cgi.escape(str(pref)), prefType, newl))
    else:
        try:
            pref.serialize(stream, basedir)
        except AttributeError:
            # 'pref' cannot be serialized (Because of PyXPCOM interface
            # flattening we do not need to QI to koISerializable to check.)
            log.error("preference '%s' (a %s) is unserializable",
                      prefName, pref)
            raise
        except TypeError, e:
            log.error("cannot serialize %r %s", pref, str(e))

if sys.version_info[0] == 2 and sys.version_info[1] < 3:
    def getChildText(node):
        return "".join([child.nodeValue for child in node.childNodes 
                        if child.nodeType == node.TEXT_NODE])
else:
    def getChildText(node):
        return "".join([child.nodeValue for child in node.childNodes 
                        if child.nodeType in [node.TEXT_NODE, node.CDATA_SECTION_NODE]])

# XXX we need to make the XMLPreferenceSetObjectFactory into a service

class koXMLPreferenceSetObjectFactory:
    """
    Creates new preference set objects from an input stream
    via a registry of deserialization objects.
    Could be instantiated as a singleton (i.e. service).
    """ 
    
    def __init__(self):
        self._deserializers = {'preference-set': koPreferenceSetDeserializer(),
                               'ordered-preference': koOrderedPreferenceDeserializer(),
                               'preference-cache': koPreferenceCacheDeserializer(),
        }

    def deserializeFile(self, filename):
        """Adds preferences to this preference set from a filename."""
        # Quickly check whether we can just load a pickled
        # version of the pref object before doing a full XML parse.
        cacheFilename = pickleCacheOKToLoad(filename)
        if cacheFilename is not None:
            log.info("cacheFilename for %r is not none, it's %r",
                     filename, cacheFilename)
            prefObject = dePickleCache(cacheFilename)
            if prefObject is not None:
                return prefObject
            else:
                log.warn("the dePickledCache object was None")
        else:
            log.info("cacheFilename for %r is None, so doing it the slow way",
                     filename)
        
        # Okay, so we have to actually parse XML.
        # Open the file (we're assuming that prefs are all local
        # files for now)
        if os.path.isfile(filename):
            stream = open(filename, "r")
            #XXX need to handle exceptions from minidom to be robust
            try:
                timeline.startTimer('minidom.parse')
                rootNode = minidom.parse(stream)
                timeline.stopTimer('minidom.parse')
            except (AttributeError, SAXParseException), e:
                #XXX why would an AttributeError be raised?
                log.exception("Couldn't deserialize file %r", filename)
                return None
            finally:
                stream.close()
        else:
            #log.debug("No prefs file %r - returning None...", filename)
            return None

        global _timers
        _timers = {}
        # Deserialize the top level preference set.
        if rootNode.hasChildNodes():
            for node in rootNode.childNodes:
                if node.nodeType == minidom.Node.ELEMENT_NODE:
                    timeline.startTimer('deserializeNode')
                    prefObject = self.deserializeNode(node, None)
                    timeline.stopTimer('deserializeNode')

        timeline.markTimer('minidom.parse')
        timeline.markTimer('deserializeNode')
        for k in _timers:
            timeline.markTimer(k)
            
        # If there wasn't a top level preference set, then
        # ... well... then there isn't one!
        return prefObject

    def deserializeNode(self, element, parentPref, basedir=None, chainNotifications=0):
        ds = self._getDeserializer(element.nodeName)
        if ds:
            deserializer_name = ds.__class__.__name__
            timeline.startTimer(deserializer_name)
            retval = ds.DOMDeserialize(element, parentPref, self, basedir, chainNotifications)
            timeline.stopTimer(deserializer_name)
            global _timers
            _timers[deserializer_name] = 1
            return retval
        else:
            log.debug("No handler for node type %s", element.nodeName)
            return None

    def registerDeserializer(self, name, ds):
        """Registers a deserializer to handle deserializing
        a particular element type.
        """
        self._deserializers[name] = ds

    def _getDeserializer(self, prefType):
        """Instantiate a deserializer given its contract id
        unless a deserializer has already been instantiated to
        handle the given preference type. We cache deserializer
        instances in self._deserializers. """
        if self._deserializers.has_key(prefType):
            return self._deserializers[prefType]
        else:
            return None




class koPreferenceCacheDeserializer:
    def DOMDeserialize(self, rootElement, parentPref, prefFactory, basedir=None, chainNotifications=0):
        xpPref = components.classes["@activestate.com/koPreferenceCache;1"] \
                  .createInstance(components.interfaces.koIPreferenceCache)
        newPref = UnwrapObject(xpPref)
        newPref.id = rootElement.getAttribute('id') or ""
        newPref.idref = rootElement.getAttribute('idref') or ""
        newPref.basedir = basedir
        try:
            max_length = int(rootElement.getAttribute('max_length'))
            newPref._maxsize = max_length
        except ValueError:
            log.error("The 'max_length' attribute is invalid")

        # Iterate over the elements of the preference set,
        # deserializing them and fleshing out the new preference
        # set with content.
        childNodes = rootElement.childNodes

        # Keep the new prefs in a list, then add them in reverse.  This
        # will magically put everything in the correct order.
        sub_prefs = []
        for node in childNodes:
            if node and node.nodeType == minidom.Node.ELEMENT_NODE:
                pref = _dispatch_deserializer(self, node, newPref, prefFactory, basedir, chainNotifications)
                if pref:
                    if pref.id:
                        sub_prefs.append(pref)
                    else:
                        log.error("Preference has no id - dumping preference:")
                        pref.dump(0)

        sub_prefs.reverse()
        for pref in sub_prefs:
            newPref.setPref(pref)

        return xpPref 


prefsetobjectfactory = koXMLPreferenceSetObjectFactory()

def deserializeFile(filename):
    return prefsetobjectfactory.deserializeFile(filename)

def NodeToPrefset(node, basedir=None, chainNotifications=0):
    return prefsetobjectfactory.deserializeNode(node, None, basedir, chainNotifications)
