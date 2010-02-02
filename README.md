# Feedie

Feedie is a feed reader for Ubuntu 9.10.

It is simple and to the point.

It is not slow and it does not crash (unlike most other feed readers I have
tried).

It does not track your reading habits and let Eric Schmidt spy on you (unlike
Google Reader).

Maybe you will like it.

## Packages

Head on over to <https://launchpad.net/~kr/+archive/ppa> if you just want to
use it.

## Development

If you check this out from git, you'll need to install a bunch of
dependencies:

    sudo apt-get install \
      python-oauth python-zope.interface python-dbus python-cheetah \
      python-couchdb python-gconf python-httplib2 python-twisted-core \
      python-twisted-web python-cairo python-gobject python-desktopcouch \
      python-feedparser python-gtk2

Then you can run it straight from the working directory with:

    ./bin/feedie

If you want to generate packages, you'll also need `cdbs` (>= 0.4.43),
`debhelper` (>= 6), and `python-distutils-extra` (>= 2.10).

## Testing

No automated tests yet. I'm working on it.
