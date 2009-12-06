import gtk
import glib
import math
import cairo
import pango
import gobject
import time

from feedie.feedieconfig import *
from feedie.util import *

class SourcesView(gtk.DrawingArea):
  __gsignals__ = dict(selection_changed=(gobject.SIGNAL_RUN_LAST,
                                         gobject.TYPE_NONE,
                                         (gobject.TYPE_PYOBJECT,)))

  def __init__(self, sources):
    gtk.DrawingArea.__init__(self)
    self.connect('expose_event', self.expose)
    self.connect('button_press_event', self.button_press)
    self.add_events(gtk.gdk.BUTTON_PRESS_MASK)
    self.lines = {}
    self.selected_id = None
    self.sources = sources
    self.sources.add_listener(self)
    self.items = {}
    self.update(self.sources)

  @property
  def selected(self):
    if not self.selected_id: return None
    if self.selected_id not in self.items: return None
    item_view = self.items[self.selected_id]
    if not item_view: return None
    return item_view.source

  def is_item_selected(self, item_id):
    return item_id == self.selected_id

  def update(self, item, arg=None):
    self.update_heading_order()
    self.update_heading_items()
    if self.selected_id not in self.items:
      self.select(None)
    self.redraw_canvas()

  def update_heading_order(self):
    names = set()
    for x in self.sources:
      names.add(x.category)
    self.heading_order = sorted(names)

  def update_heading_items(self):
    old = self.items
    self.items = dict([(x.id, old.get(x.id, SourceItem(self, x))) for x in self.sources])

    by_heading = {}
    for x in self.sources:
      by_heading.setdefault(x.category, []).append(self.items[x.id])
    self.heading_items = by_heading

  def button_press(self, widget, event):
    line = int(event.y / self.line_height())
    item = self.lines.get(line, None)
    if item:
      self.select(item.id)

  def select(self, item_id):
    if self.selected_id != item_id:
      self.selected_id = item_id
      self.redraw_canvas()
      self.emit('selection-changed', self.selected_id)

  def expose(self, widget, event):
    self.context = widget.window.cairo_create()

    # set a clip region for the expose event
    self.context.rectangle(event.area.x, event.area.y,
                           event.area.width, event.area.height)
    self.context.clip()

    self.draw(self.context)
    return False

  def text_height(self):
    height = self.context.font_extents()[2]
    return int(height)

  def line_height(self):
    return max(self.text_height() + self.text_height() / 2, 20)

  def leading(self):
    return leading(self.line_height(), self.text_height())

  def baseline_offset(self):
    ascent = self.context.font_extents()[0]
    return ascent + self.leading() / 2 - 0.5

  def draw_line(self, line, f, *args, **kwargs):
    self.context.save()
    try:
      self.context.translate(0, line * self.line_height())
      return f(*args, **kwargs)
    finally:
      self.context.restore()

  def draw(self, context):
    rect = self.get_allocation()
    x = rect.x + rect.width / 2
    y = rect.y + rect.height / 2

    radius = min(rect.width / 2, rect.height / 2) - 5

    # background
    context.set_source_rgb(0.82, 0.85, 0.90)
    context.rectangle(0, 0, rect.width, rect.height)
    context.fill()

    self.context.set_font_size(font_size)
    line = 0
    self.lines = {}
    for heading_name in self.heading_order:
      items = self.heading_items[heading_name]
      self.draw_line(line, draw_heading, self, context, heading_name)
      line += 1
      for item in items:
        if item.is_selectable(): self.lines[line] = item
        self.draw_line(line, item.draw, context)
        line += 1
      line += 1 # margin

  def flash(self, item_id):
    self.items[item_id].flash()
    glib.idle_add(self.update_flash_anim)

  def update_flash_anim(self):
    self.redraw_canvas()
    for item in self.items.values():
      if item.is_flashing(): return True
    return False

  def redraw_canvas(self):
    if self.window:
      alloc = self.get_allocation()
      rect = gtk.gdk.Rectangle(0, 0, alloc.width, alloc.height)
      self.window.invalidate_rect(rect, True)

def draw_heading(sourceview, context, text):
  baseline = sourceview.baseline_offset()
  #text = u'\u25bc ' + text
  text = text.upper()

  context.select_font_face(font_desc.get_family(),
      cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)

  context.set_source_rgba(1, 1, 1, 0.5)
  context.move_to(10, baseline + 1)
  context.show_text(text)

  context.set_source_rgb(0.447, 0.498, 0.584)
  context.move_to(10, baseline)
  context.show_text(text)

class SourceSeparatorItem:
  def __init__(self, heading):
    self.heading = heading
    self.sourceview = heading.sourceview

  def is_selectable(self):
    return False

  def draw(self, context):
    line_height = self.sourceview.line_height()
    line_width = self.sourceview.get_allocation().width

    sep_height = 1
    sep_width = line_width - 20

    top = (line_height - sep_height) / 2
    left = (line_width - sep_width) / 2

    context.set_source_rgba(0, 0, 0, 0.1)
    context.rectangle(left, top, sep_width, sep_height)
    context.fill()

class SourceItem:
  def __init__(self, sourceview, source):
    self.source = source
    self.sourceview = sourceview
    if source.unread > 0:
      self.label = '%s (%d)' % (source.title, source.unread)
    else:
      self.label = source.title
    self.icon = source.icon
    self.id = source.id
    self.flash_go = False
    self.flash_start = 0
    source.add_listener(self)

  @property
  def is_selected(self):
    return self.sourceview.is_item_selected(self.id)

  def update(self, item, arg=None):
    if self.source.unread > 0:
      self.label = '%s (%d)' % (self.source.title, self.source.unread)
    else:
      self.label = self.source.title
    self.icon = self.source.icon
    self.id = self.source.id
    self.sourceview.redraw_canvas()

  def is_selectable(self):
    return True

  def flash(self):
    self.flash_go = True

  def is_flashing(self):
    return self.flash_go or self.flash_prog() < 1.1 # add a little fudge

  def flash_prog(self):
    return (time.time() - self.flash_start) / 1.5

  def draw_flash(self, context):
    if self.flash_go:
      self.flash_go = False
      self.flash_start = time.time()

    height = self.sourceview.line_height()
    width = self.sourceview.get_allocation().width
    prog = self.flash_prog()
    if prog < 0.5:
      prog *= 2
    elif prog < 1.0:
      prog -= 0.5
      prog *= 2
    else:
      return

    pulse_width = 0.2
    pulse_hwidth = pulse_width * 0.5

    prog *= 1.0 + pulse_width
    prog -= pulse_hwidth

    if self.is_selected:
      color = (0.95, 0.85, 0.4)
    else:
      color = (0.4, 0.4, 0.4)

    linear = cairo.LinearGradient(0, 0, width, 0)
    linear.add_color_stop_rgba(0.0,                 *color + (0,))
    linear.add_color_stop_rgba(prog - pulse_hwidth, *color + (0,))
    linear.add_color_stop_rgba(prog,                *color + (1,))
    linear.add_color_stop_rgba(prog + pulse_hwidth, *color + (0,))
    linear.add_color_stop_rgba(1.0,                 *color + (0,))
    context.set_source(linear)
    context.rectangle(0, 0, width, height)
    context.fill()

  def draw_icon(self, context):
    height = self.sourceview.line_height()
    #icon = cairo.ImageSurface.create_from_png(self.icon_path)
    theme = gtk.icon_theme_get_default()
    try:
      icon = theme.load_icon(self.icon, 16, 0)
    except:
      icon = None

    shift = 0
    if icon:
      context.set_source_pixbuf(icon, 20, leading(height, 16) / 2)
      context.paint()
      shift = 20 # icon width + 4
    return shift

  def draw(self, context):
    baseline = self.sourceview.baseline_offset()

    text = self.label

    height = self.sourceview.line_height()
    if self.is_selected:
      width = self.sourceview.get_allocation().width

      linear = cairo.LinearGradient(0, 0, 0, height)
      linear.add_color_stop_rgb(0, 0.153, 0.420, 0.851)
      linear.add_color_stop_rgb(1, 0.129, 0.361, 0.729)
      context.set_source(linear)
      context.rectangle(0, 0, width, height)
      context.fill()

      context.set_source_rgb(0.129, 0.361, 0.729)
      context.move_to(0 + 0.5, 0 + 0.5)
      context.line_to(width + 0.5, 0 + 0.5)
      context.set_line_width(1)
      context.stroke()

      self.draw_flash(context)

      shift = self.draw_icon(context)

      context.select_font_face(font_desc.get_family(),
          cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)

      context.set_source_rgba(0, 0, 0, 0.5)
      context.move_to(20 + shift, baseline + 1)
      context.show_text(text)

      context.set_source_rgb(*mix(1.0, (0.153, 0.420, 0.851), (1, 1, 1)))
      context.move_to(20 + shift, baseline)
      context.show_text(text)
    else:
      self.draw_flash(context)

      shift = self.draw_icon(context)


      context.select_font_face(font_desc.get_family(),
          cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)

      context.set_source_rgba(0, 0, 0, 1)
      context.move_to(20 + shift, baseline)
      context.show_text(text)

