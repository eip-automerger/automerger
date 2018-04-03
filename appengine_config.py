from google.appengine.ext import vendor

# Add any libraries installed in the "lib" folder.
vendor.add('lib')

from requests_toolbelt.adapters import appengine
appengine.monkeypatch()
