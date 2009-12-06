# -*- coding: utf-8 -*-
### BEGIN LICENSE
# This file is in the public domain
### END LICENSE

# THIS IS Feedie CONFIGURATION FILE
# YOU CAN PUT THERE SOME GLOBAL VALUE
# Do not touch until you know what you're doing.
# you're warned :)

# where your project will head for your data (for instance, images and ui files)
# by default, this is ../data, relative your trunk layout
__feedie_data_directory__ = '../data/'


import os
import gtk
import pango

font_desc = gtk.Style().font_desc
font_size = gtk.Style().font_desc.get_size() * 96 / 72 / pango.SCALE

class project_path_not_found(Exception):
    pass

def getdatapath():
    """Retrieve feedie data path

    This path is by default <feedie_lib_path>/../data/ in trunk
    and /usr/share/feedie in an installed version but this path
    is specified at installation time.
    """

    # get pathname absolute or relative
    if __feedie_data_directory__.startswith('/'):
        pathname = __feedie_data_directory__
    else:
        pathname = os.path.dirname(__file__) + '/' + __feedie_data_directory__

    abs_data_path = os.path.abspath(pathname)
    if os.path.exists(abs_data_path):
        return abs_data_path
    else:
        raise project_path_not_found

