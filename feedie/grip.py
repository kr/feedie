import gtk

# Why oh why is this not a widget in gtk? I don't want a statusbar, just a
# resize grip!
class ResizeGrip(gtk.DrawingArea):
  __gsignals__ = {
    'expose-event': 'override',
    'button-press-event': 'override',
  }

  # These are in effect the max/default size of the grip.
  w = 18
  h = 18

  def __init__(self):
    gtk.DrawingArea.__init__(self)
    self.set_size_request(self.w, self.h)
    self.add_events(gtk.gdk.BUTTON_PRESS_MASK)
    self.connect('realize', self.realize_cb)

  def realize_cb(self, *args):
    self.set_grip_cursor()

  def set_grip_cursor(self):
    if self.get_direction() == gtk.TEXT_DIR_LTR:
      cursor_type = gtk.gdk.BOTTOM_RIGHT_CORNER;
    else:
      cursor_type = gtk.gdk.BOTTOM_LEFT_CORNER;

    cursor = gtk.gdk.Cursor(self.get_display(), cursor_type)
    self.window.set_cursor(cursor)

  def do_button_press_event(self, event):
    window = self.get_toplevel()

    if not isinstance(window, gtk.Window):
      return False

    if event.button == 1:
      window.begin_resize_drag(
          self.edge,
          event.button,
          int(event.x_root),
          int(event.y_root),
          event.time)

    return True

  def do_expose_event(self, event):
    rect = self.get_grip_rect()
    self.style.paint_resize_grip(
        self.window,
        self.state,
        event.area,
        self,
        'statusbar',
        self.edge,
        rect.x,
        rect.y,
        rect.width,
        rect.height)

  @property
  def edge(self):
    if self.get_direction() == gtk.TEXT_DIR_LTR:
      return gtk.gdk.WINDOW_EDGE_SOUTH_EAST
    else:
      return gtk.gdk.WINDOW_EDGE_SOUTH_WEST

  def get_grip_rect(self):
    allocation = self.get_allocation()

    w = self.w
    h = self.h

    if w > allocation.width:
      w = allocation.width

    if h > allocation.height - self.style.ythickness:
      h = allocation.height - self.style.ythickness

    rect = gtk.gdk.Rectangle()

    rect.width = w
    rect.height = h

    rect.y = allocation.height - h # on bottom edge

    if self.get_direction() == gtk.TEXT_DIR_LTR:
      rect.x = allocation.width - w # on right-hand edge
    else:
      rect.x = self.style.xthickness # on left-hand edge

    return rect



