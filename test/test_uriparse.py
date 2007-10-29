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

import os
import unittest
import sys, md5
import tempfile

from xpcom import components, COMException

import uriparse
win32 = sys.platform.startswith("win")

class Test_uriparse(unittest.TestCase):
    paths = [
        ("path", "Normal windows local path",
                r"c:\test\test.txt", "file:///c:/test/test.txt"),
        ("path", "Windows UNC path",
                r"\\planer\d\trentm\tmp\foo.txt", "file://planer/d/trentm/tmp/foo.txt"),
    ]
    urls = [
        ("url",  "Windows UNC URI (2 slashes)", "file://planer/d/trentm/tmp/foo.txt",
                r"\\planer\d\trentm\tmp\foo.txt"),
        ("url",  "Windows UNC URI (5 slashes)", "file://///planer/d/trentm/tmp/foo.txt",
                r"\\planer\d\trentm\tmp\foo.txt"),
        ("url",  "File URI with spaces", "file://breakfast/spam and eggs.txt",
                r"\\breakfast\spam and eggs.txt"),
        #("url",  "Windows UNC URI (1 slashes)", "file:/planer/d/trentm/tmp/foo.txt"),
        #("url",  "Windows UNC URI (3 slashes)", "file:///planer/d/trentm/tmp/foo.txt"),
        #("url",  "Windows UNC URI (4 slashes)", "file:////planer/d/trentm/tmp/foo.txt"),
    ]
    relative = [
        # base, relative, full, common
        (r'c:\test',r'test.txt',r'c:\test\test.txt', r'c:\test'),
        ('/test','/testing/file.txt','/testing/file.txt', ''),
        (r'c:\test',r'c:\testing\file.txt',r'c:\testing\file.txt', 'c:'),
        (r'd:\test',r'c:\testing\file.txt',r'c:\testing\file.txt', ''),
    ]
    full_relativize = [
        ('/home/shanec/test/somepath','../bad/a:b','/home/shanec/test/bad/a:b','/home/shanec/test'),
        ('/test/a/b','../testing/file.txt','/test/a/testing/file.txt', '/test/a'),
        ('/home/shanec/test/somepath/anotherpath/andyetanother','../../../bad/a:b','/home/shanec/test/bad/a:b','/home/shanec/test'),
        (r'c:\test\a\b',r'..\testing\file.txt',r'c:\test\a\testing\file.txt', r'c:\test\a'),
    ]

    def __init__(self, methodName):
        unittest.TestCase.__init__(self, methodName)
        initSvc = components.classes["@activestate.com/koInitService;1"] \
                      .getService(components.interfaces.koIInitService)
        initSvc.setEncoding()
        
        self.__file = components.classes["@activestate.com/koFileEx;1"] \
                      .createInstance(components.interfaces.koIFileEx)

    def failUnlessSamePath(self, p1, p2):
        _p1 = p1.replace('\\','/')
        _p2 = p2.replace('\\','/')
        self.failUnlessEqual(_p1, _p2, "%r != %r"%(p1,p2))

    def test_localpaths(self):
        for test in self.paths:
            uri = uriparse.localPathToURI(test[2].replace("\\","/"))
            self.failUnlessSamePath(uri,test[3].replace("\\","/"))

    def test_urls(self):
        for test in self.urls:
            path = uriparse.URIToLocalPath(test[2])
            self.failUnlessSamePath(path,test[3])

    def test_commonprefix(self):
        for base, rel, full, common in self.relative:
            c = uriparse.commonprefix(base, full)
            self.failUnlessSamePath(c, common)

    def test_relativize(self):
        for base, rel, fullpath, common in self.relative:
            path = uriparse.RelativizeURL(base, fullpath)
            self.failUnlessSamePath(path, rel)

    def test_fullrelativize(self):
        relative = self.relative + self.full_relativize
        for base, rel, fullpath, common in relative:
            path = uriparse.RelativizeURL(base, fullpath, 1)
            self.failUnlessSamePath(path, rel)

    def test_UNrelativize(self):
        import URIlib
        relative = self.relative + self.full_relativize
        for base, rel, fullpath, common in relative:
            URI = uriparse.UnRelativizeURL(base, rel)
            fullURI = URIlib.URIParser(URI)
            self.failUnlessSamePath(fullURI.path, fullpath)
            

class _dummyPrefsClass(object):
    def __init__(self, string_prefs=None):
        self.parent = None
        if string_prefs is None:
            self.string_dict = {}
        else:
            self.string_dict = string_prefs
    # XXX: What does PrefHere do?
    def hasPrefHere(self, pref_name):
        return pref_name in self.string_dict
    def hasStringPref(self, pref_name):
        return pref_name in self.string_dict
    def getStringPref(self, pref_name):
        return self.string_dict.get(pref_name, "")

class Test_URIMapping(unittest.TestCase):
    def test_getMappedURI(self):
        mappingdata_for_mappedPaths = {
            "": {
                "file:///tmp/file1.txt":        "file:///tmp/file1.txt",
                "http://server/tmp/file2.txt":  "http://server/tmp/file2.txt",
                "file:///f.c":                  "file:///f.c",
                "sftp://remote/tmp/file3.txt":  "sftp://remote/tmp/file3.txt",
                "C:\\tmp\\file4.txt":           "C:\\tmp\\file4.txt",
                },
            "http://server/tmp##/tmp::"\
            "sftp://remote##/remote": {
                "file:///tmp/file1.txt":        "file:///tmp/file1.txt",
                "http://server/tmp/file2.txt":  "file:///tmp/file2.txt",
                "file:///f.c":                  "file:///f.c",
                "sftp://remote/tmp/file3.txt":  "file:///remote/tmp/file3.txt",
                "C:\\tmp\\file4.txt":           "C:\\tmp\\file4.txt",
                },
        }
        for mappedPath, mappingData in mappingdata_for_mappedPaths.items():
            prefs = _dummyPrefsClass({"mappedPaths": mappedPath})
            for uri, expected_uri in mappingData.items():
                mapped_uri = uriparse.getMappedURI(uri, prefs)
                self.failUnlessEqual(mapped_uri, expected_uri,
                                     "Mapped URI was not expected: %r != %r" %
                                     (mapped_uri, expected_uri))

    def test_getMappedPath(self):
        mappingdata_for_mappedPaths = {
            "": {
                "/tmp/file1.txt":         "/tmp/file1.txt",
                "/server/tmp/file2.txt":  "/server/tmp/file2.txt",
                "/f.c":                   "/f.c",
                "/remote/tmp/file3.txt":  "/remote/tmp/file3.txt",
                "C:\\tmp\\file4.txt":     "C:\\tmp\\file4.txt",
                },
            "http://server/tmp##/tmp::"\
            "sftp://remote##/remote": {
                "/tmp/file1.txt":         "http://server/tmp/file1.txt",
                "/server/tmp/file2.txt":  "/server/tmp/file2.txt",
                "/f.c":                   "/f.c",
                "/remote/tmp/file3.txt":  "sftp://remote/tmp/file3.txt",
                "C:\\tmp\\file4.txt":     "C:\\tmp\\file4.txt",
                },
        }
        for mappedPath, mappingData in mappingdata_for_mappedPaths.items():
            prefs = _dummyPrefsClass({"mappedPaths": mappedPath})
            for path, expected_uri in mappingData.items():
                mapped_uri = uriparse.getMappedPath(path, prefs)
                self.failUnlessEqual(mapped_uri, expected_uri,
                                     "Mapped URI was not expected: %r != %r" %
                                     (mapped_uri, expected_uri))

    def test_getMappedPathForHost(self):
        mappingdata_for_mappedPaths = {
            "": ({
                "/tmp/file1.txt":         "/tmp/file1.txt",
                "/server/tmp/file2.txt":  "/server/tmp/file2.txt",
                "/f.c":                   "/f.c",
                "/remote/tmp/file3.txt":  "/remote/tmp/file3.txt",
                "C:\\tmp\\file4.txt":     "C:\\tmp\\file4.txt",
                },
                ""),
            "http://server/tmp##/tmp::"\
            "sftp://remote##/remote": ({
                "/tmp/file1.txt":         "http://server/tmp/file1.txt",
                "/server/tmp/file2.txt":  "/server/tmp/file2.txt",
                "/f.c":                   "/f.c",
                "/remote/tmp/file3.txt":  "/tmp/file3.txt",
                "C:\\tmp\\file4.txt":     "C:\\tmp\\file4.txt",
                },
                "server"),
            "http://server/tmp##/tmp::"\
            "sftp://remote##/remote": ({
                "/tmp/file1.txt":         "/tmp/file1.txt",
                "/server/tmp/file2.txt":  "/server/tmp/file2.txt",
                "/f.c":                   "/f.c",
                "/remote/tmp/file3.txt":  "sftp://remote/tmp/file3.txt",
                "C:\\tmp\\file4.txt":     "C:\\tmp\\file4.txt",
                },
                "remote"),
        }
        for mappedPath, mappingData in mappingdata_for_mappedPaths.items():
            mappingData, host = mappingData
            prefs = _dummyPrefsClass({"mappedPaths": mappedPath})
            for path, expected_uri in mappingData.items():
                mapped_uri = uriparse.getMappedPath(path, prefs, host)
                self.failUnlessEqual(mapped_uri, expected_uri,
                                     "Mapped URI was not expected: %r != %r" %
                                     (mapped_uri, expected_uri))

    #@tag("knownfailure")
    def test_URIUnmapping(self):
        # Testcase to show where the current mapped uri system falls down
        mappingdata_for_mappedPaths = {
            "": {
                "file://myserver/tmp/file1.txt":  "file://myserver/tmp/file1.txt",
            },
            "file://myserver/tmp##file://C:/tmp": {
                "file://myserver/tmp/file1.txt":  "file:///C:/tmp/file1.txt",
            },
            "file://myserver/tmp##C:\\tmp": {
                "file://myserver/tmp/file1.txt":  "file:///C:/tmp/file1.txt",
            },
        }
        for mappedPath, mappingData in mappingdata_for_mappedPaths.items():
            prefs = _dummyPrefsClass({"mappedPaths": mappedPath})
            for path, expected_uri in mappingData.items():
                mapped_uri = uriparse.getMappedURI(path, prefs)
                self.failUnlessEqual(mapped_uri, expected_uri,
                                     "Mapped URI was not expected: %r != %r (mappedPath: %r)" %
                                     (mapped_uri, expected_uri, mappedPath))
                unmapped_path = uriparse.getMappedPath(mapped_uri, prefs)
                self.failUnlessEqual(unmapped_path, path,
                                     "Mapped URI was not unmapped correctly: %r != %r (mappedPath: %r)" %
                                     (unmapped_path, path, mappedPath))


#---- mainline

def suite():
    testsuite1 = unittest.makeSuite(Test_uriparse)
    testsuite2 = unittest.makeSuite(Test_URIMapping)
    return unittest.TestSuite([testsuite1, testsuite2])

def test_main():
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite())

if __name__ == "__main__":
    __file__ = os.path.abspath(sys.argv[0]) # won't be necessary in Python 2.3
    test_main()

