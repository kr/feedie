# -*- coding: utf-8 -*-
### BEGIN LICENSE
# This file is in the public domain
### END LICENSE

import sys
import os
import gtk
import gconf

from feedie.feedieconfig import getdatapath

gconf_client = gconf.client_get_default()

class PreferencesFeedieDialog(gtk.Dialog):
    __gtype_name__ = "PreferencesFeedieDialog"

    url_handler_path = '/desktop/gnome/url-handlers/feed'
    url_handler_command = 'feedie %s'

    col_label = 0
    col_days = 1

    def __init__(self):
        """__init__ - This function is typically not called directly.
        Creation of a PreferencesFeedieDialog requires redeading the associated ui
        file and parsing the ui definition extrenally,
        and then calling PreferencesFeedieDialog.finish_initializing().

        Use the convenience function NewPreferencesFeedieDialog to create
        NewAboutFeedieDialog objects.
        """

        pass

    def finish_initializing(self, builder, prefs):
        """finish_initalizing should be called after parsing the ui definition
        and creating a AboutFeedieDialog object with it in order to finish
        initializing the start of the new AboutFeedieDialog instance.
        """

        #get a reference to the builder and set up the signals
        self.builder = builder
        self.builder.connect_signals(self)

        self.is_default_feed_reader_label = self.builder.get_object('is_default_feed_reader_label')
        self.is_not_default_feed_reader_label = self.builder.get_object('is_not_default_feed_reader_label')
        self.make_default_button = self.builder.get_object('make_default_button')

        def gconf_url_handler_notify(gc, path, ptr):
          self.update_default_reader_display()

        gconf_client.add_dir(self.url_handler_path,
            gconf.CLIENT_PRELOAD_ONELEVEL)
        self._handler_id = gconf_client.connect('value-changed',
            gconf_url_handler_notify)
        self.update_default_reader_display()

        self._disconnect = []

        self.keep_days_menu = self.builder.get_object('keep_days_menu')
        self.keep_days_desc = self.builder.get_object('keep_days_desc')

        def keep_days_changed(*args):
          self.update_keep_days_menu()

        self.prefs = prefs
        f = prefs.connect('keep-days-changed', keep_days_changed)
        self._disconnect.append(f)
        self.update_keep_days_menu()

    def update_keep_days_menu(self):
      n = self.prefs.keep_days
      model = self.keep_days_menu.get_model()
      for x in model:
        i = x.path[0]
        if x[self.col_days] == n:
          self.keep_days_menu.set_active(i)

      if n > 1000000: # forever :)
        self.keep_days_desc.hide()
      else:
        self.keep_days_desc.show()

    def update_default_reader_display(self):
      feed_handler = gconf_client.get_string(self.url_handler_path + '/command')
      enabled = gconf_client.get_bool(self.url_handler_path + '/enabled')
      needs_terminal = gconf_client.get_bool(self.url_handler_path + '/needs_terminal')

      is_default = True
      if feed_handler != self.url_handler_command:
        is_default = False
      elif not enabled:
        is_default = False
      elif needs_terminal:
        is_default = False

      if is_default:
        self.is_default_feed_reader_label.show()
        self.is_not_default_feed_reader_label.hide()
        self.make_default_button.props.sensitive = False
      else:
        self.is_default_feed_reader_label.hide()
        self.is_not_default_feed_reader_label.show()
        self.make_default_button.props.sensitive = True

    def make_default(self, *args):
      gconf_client.set_string(self.url_handler_path + '/command',
          self.url_handler_command)
      gconf_client.set_bool(self.url_handler_path + '/enabled', True)
      gconf_client.set_bool(self.url_handler_path + '/needs_terminal', False)

    def housekeeping_changed(self, *args):
      model = self.keep_days_menu.get_model()
      path = self.keep_days_menu.get_active()
      row = model[path]
      self.prefs.keep_days = row[self.col_days]

    def on_destroy(self, *args):
      gconf_client.disconnect(self._handler_id)
      gconf_client.remove_dir(self.url_handler_path)
      while self._disconnect:
        f = self._disconnect.pop()
        f()

def NewPreferencesFeedieDialog(prefs):
    """NewPreferencesFeedieDialog - returns a fully instantiated
    PreferencesFeedieDialog object. Use this function rather than
    creating a PreferencesFeedieDialog instance directly.
    """

    #look for the ui file that describes the ui
    ui_filename = os.path.join(getdatapath(), 'ui', 'PreferencesFeedieDialog.ui')
    if not os.path.exists(ui_filename):
        ui_filename = None

    builder = gtk.Builder()
    builder.add_from_file(ui_filename)
    dialog = builder.get_object("preferences_feedie_dialog")
    dialog.finish_initializing(builder, prefs)
    return dialog

if __name__ == "__main__":
    dialog = NewPreferencesFeedieDialog(prefs)
    dialog.show()
    gtk.main()

