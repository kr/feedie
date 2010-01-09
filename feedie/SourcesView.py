import gtk
import glib
import math
import cairo
import pango
import gobject
import time
import locale
import colorsys
from math import pi, ceil
from collections import namedtuple

from feedie.feedieconfig import *
from feedie.util import *
from feedie import graphics

Layout = namedtuple('Layout', 'items rev')

class SourcesView(gtk.DrawingArea):
  __gsignals__ = dict(selection_changed=(gobject.SIGNAL_RUN_LAST,
                                         gobject.TYPE_NONE,
                                         (gobject.TYPE_PYOBJECT,)))

  _rsv = {
    'list-bg': (
      (.00, 0.0652, 0.9020), # neither
      (.00, 0.0652, 0.9020), # only selected
      (.00, 0.0652, 0.9020), # only focused
      (.00, 0.0652, 0.9020), # selected and focused
    ),
    'item-bg-bottom': (
      (.00, 0.8230, 0.7290),
      (.00, 0.8230, 0.7290),
      (.00, 0.8230, 0.7290),
      (.00, 0.8230, 0.7290),
    ),
    'item-fg': (
      (.00, 0.0000, 0.1000),
      (.00, 0.0000, 1.0000),
      (.00, 0.0000, 0.2000),
      (.00, 0.0000, 1.0000),
    ),
    'item-fg-shadow': (
      (.00, 0.0652, 0.9020),
      (.00, 0.8230, 0.3290),
      (.00, 0.0652, 0.9020),
      (.00, 0.8230, 0.3290),
    ),
    'heading-fg': (
      (.00, 0.2346, 0.5840),
      (.00, 0.2346, 0.5840),
      (.00, 0.2346, 0.5840),
      (.00, 0.2346, 0.5840),
    ),
    'heading-fg-shadow': (
      (.00, 0.0000, 0.9500),
      (.00, 0.0000, 0.9500),
      (.00, 0.0000, 0.9500),
      (.00, 0.0000, 0.9500),
    ),
    'pill-bg': (
      (.00, 0.4327, 0.8157),
      (.00, 0.0000, 1.0000),
      (.00, 0.4327, 0.8157),
      (.00, 0.0000, 1.0000),
    ),
    'pill-fg': (
      (.00, 0.0000, 1.0000),
      (.00, 0.0000, 0.3500),
      (.00, 0.0000, 1.0000),
      (.00, 0.0000, 0.3500),
    ),
    'pulse': (
      (.00, 0.0000, 0.4000),
      (.54, 0.5789, 0.9500),
      (.00, 0.0000, 0.4000),
      (.54, 0.5789, 0.9500),
    ),
    'pie': (
      (.00, 0.0652, 0.4500),
      (.00, 0.0652, 1.0000),
      (.00, 0.0652, 0.4500),
      (.00, 0.0652, 1.0000),
    ),
  }

  def __init__(self, sources):
    gtk.DrawingArea.__init__(self)
    self.connect('expose_event', self.expose)
    self.connect('button_press_event', self.button_press)
    self.add_events(gtk.gdk.BUTTON_PRESS_MASK)
    self.selected_id = None
    self.sources = sources
    self.sources.connect('sources-added', self.sources_added)
    self.sources.connect('source-removed', self.source_removed)
    self.items = {}
    self.order = []
    self.compute_line_height()
    self.add_sources(self.sources)
    self.connect('style-set', self.style_set_cb)
    self.hue = 0.6

  @property
  def hue(self):
    return self._hue

  @hue.setter
  def hue(self, h):
    self._hue = h
    self._color = {}
    for name, rsv in self._rsv.items():
      f = colorsys.hsv_to_rgb
      self._color[name] = tuple(f(h + r, s, v) for r,s,v in rsv)

  def color(self, name, selected=True, focused=True):
    i = 2 * int(bool(focused)) + int(bool(selected))
    return self._color[name][i]

  def set_color(self, cairo_context, name, selected=True, focused=True):
    color = self.color(name, selected=selected, focused=focused)
    cairo_context.set_source_rgb(*color)

  @property
  def selected_view(self):
    if not self.selected_id: return None
    if self.selected_id not in self.items: return None
    return self.items[self.selected_id]

  @property
  def selected(self):
    view = self.selected_view
    if not view: return None
    return view.source

  def is_item_selected(self, item_id):
    return item_id == self.selected_id

  def add_sources(self, sources):
    for source in sources:
      if source.id not in self.items:
        self.items[source.id] = SourceItem(self, source)
        self.order.append(self.items[source.id])
    self.order.sort(key=lambda x: x.source.sort_key)
    self.post_update()

  def remove_source(self, source):
    # TODO disconnect event handlers in SourceItem
    if source.id in self.items:
      item = self.items[source.id]
      del self.items[source.id]
      if item in self.order: self.order.remove(item)
      self.post_update()

  def sources_added(self, manager, event, sources):
    self.add_sources(sources)

  def source_removed(self, sources, event, source):
    self.remove_source(source)

  def post_update(self):
    del self.layout
    self.update_size_request()
    if self.selected_id not in self.items:
      self.select(None)
    self.queue_draw()

  def style_set_cb(self, *args):
    self.compute_line_height()
    self.update_size_request()

  def update_size_request(self):
    self.set_size_request(-1, self.height_request)

  @property
  def height_request(self):
    return self.line_height * len(self.layout.items)

  def button_press(self, widget, event):
    line = int(event.y / self.line_height)
    if line >= 0 and line < len(self.layout.items):
      item = self.layout.items[line]
      if hasattr(item, 'id'):
        self.select(item.id)

  @property
  def layout(self):
    if not hasattr(self, '_layout'):
      items, rev = self._layout = Layout([], {})

      items.append(HeadingItem(self, 'News'))
      for item in self.order:
        rev[item.id] = len(items)
        items.append(item)
      #items.append(BlankItem())

    return self._layout

  @layout.deleter
  def layout(self):
    if hasattr(self, '_layout'):
      del self._layout

  def get_y(self, item_id):
    return self.line_height * self.layout.rev.get(item_id, 0)

  def select(self, item_id):
    if self.selected_id != item_id:
      prev = self.selected_view
      self.selected_id = item_id
      if prev: prev.queue_draw()
      if self.selected_view: self.selected_view.queue_draw()
      self.emit('selection-changed', self.selected_id)

  def expose(self, widget, event):
    cairo_context = widget.window.cairo_create()

    # set a clip region for the expose event
    cairo_context.rectangle(event.area.x, event.area.y,
                           event.area.width, event.area.height)
    cairo_context.clip()

    self.draw(cairo_context, event.area)
    return False

  @property
  def pango_context(self):
    return self.get_pango_context()

  @property
  def font_desc(self):
    return self.get_style().font_desc

  @property
  def approx_text_height(self):
    fd = self.font_desc
    metrics = self.pango_context.get_metrics(fd, None)
    return (metrics.get_ascent() + metrics.get_descent()) / pango.SCALE

  def compute_line_height(self):
    text_height = self.approx_text_height
    self.line_height = max(text_height + text_height / 2 - 1, 10)

  @property
  def width(self):
    rect = self.get_allocation()
    return rect.width

  def draw(self, cairo_context, area):
    def draw_line(line, item, *args, **kwargs):
      cairo_context.save()
      try:
        cairo_context.translate(0, line * self.line_height)
        return item.draw(*args, **kwargs)
      finally:
        cairo_context.restore()

    if area.width < 1 or area.height < 1: return # can't happen

    top = len(self.layout.items)

    def clamp(n):
      return min(max(n, 0), top)

    start_line = clamp(int(area.y / self.line_height))
    stop_line = clamp(int(ceil((area.y + area.height) * 1.0 / self.line_height)))

    # background
    self.set_color(cairo_context, 'list-bg')
    cairo_context.rectangle(area.x, area.y, area.width, area.height)
    cairo_context.fill()

    for line in range(start_line, stop_line):
      draw_line(line, self.layout.items[line], cairo_context)

  def flash(self, item_id):
    if item_id not in self.items: return
    self.items[item_id].flash()
    glib.timeout_add(17, self.update_flash_anim)

  def update_flash_anim(self):
    ret = False
    # TODO functionalize
    for item in self.items.values():
      if item.is_flashing():
        item.queue_draw()
        ret = True
    return ret

  def draw_text(self, font_desc, cairo_context, text, color_name, width, height, dx, dy,
      selected=True,
      focused=True):
    if width < 1: return

    self.set_color(cairo_context, color_name,
        selected=selected,
        focused=focused)

    layout = cairo_context.create_layout()
    layout.set_width(width * pango.SCALE)
    layout.set_wrap(False)
    layout.set_ellipsize(pango.ELLIPSIZE_END)
    layout.set_font_description(font_desc)
    layout.set_text(text)
    text_width, text_height = layout.get_pixel_size()
    cairo_context.move_to(dx, leading(height, text_height) / 2 + dy)
    cairo_context.show_layout(layout)

class HeadingItem:
  def __init__(self, sourceview, label):
    self.label = label
    self.sourceview = sourceview

  def draw(self, cairo_context):
    baseline = 5
    text = self.label.upper()
    sourceview = self.sourceview

    label_width = sourceview.width - 10

    fd = sourceview.font_desc.copy()
    fd.set_weight(700)
    self.sourceview.draw_text(fd, cairo_context, text,
        'heading-fg-shadow', label_width, sourceview.line_height, 10, 1)

    self.sourceview.draw_text(fd, cairo_context, text,
        'heading-fg', label_width, sourceview.line_height, 10, 0)

class SourceSeparatorItem:
  def __init__(self, heading):
    self.heading = heading
    self.sourceview = heading.sourceview

  def is_selectable(self):
    return False

  def draw(self, cairo_context):
    line_height = self.sourceview.line_height
    line_width = self.sourceview.get_allocation().width

    sep_height = 1
    sep_width = line_width - 20

    top = (line_height - sep_height) / 2
    left = (line_width - sep_width) / 2

    cairo_context.set_source_rgba(0, 0, 0, 0.1)
    cairo_context.rectangle(left, top, sep_width, sep_height)
    cairo_context.fill()

class SourceItem:
  def __init__(self, sourceview, source):
    self.source = source
    self.sourceview = sourceview
    self.flash_go = False
    self.flash_start = 0
    self.icon = None
    source.connect('summary-changed', self.summary_changed)
    source.connect('favicon-changed', self.favicon_changed)

  @property
  def id(self):
    return self.source.id

  @property
  def label(self):
    return self.source.title

  @property
  def is_selected(self):
    return self.sourceview.is_item_selected(self.source.id)

  @property
  def x(self):
    return 0

  @property
  def y(self):
    return self.sourceview.get_y(self.id)

  @property
  def width(self):
    return self.sourceview.get_allocation().width

  @property
  def height(self):
    return self.sourceview.line_height

  def summary_changed(self, source, event):
    self.queue_draw()

  def favicon_changed(self, source, event):
    self.icon = None
    self.queue_draw()

  def queue_draw_area(self, x, y, width, height):
    self.sourceview.queue_draw_area(self.x + x, self.y + y, width, height)

  def queue_draw(self):
    self.queue_draw_area(0, 0, self.width, self.height)

  def is_selectable(self):
    return True

  def flash(self):
    self.flash_go = True

  def is_flashing(self):
    return self.flash_go or self.flash_prog() < 1.1 # add a little fudge

  def flash_prog(self):
    return (time.time() - self.flash_start) / 1.5

  def draw_flash(self, cairo_context):
    if self.flash_go:
      self.flash_go = False
      self.flash_start = time.time()

    height = self.sourceview.line_height
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
    color = self.sourceview.color('pulse', selected=self.is_selected)

    linear = cairo.LinearGradient(0, 0, width, 0)
    linear.add_color_stop_rgba(0.0,                 *color + (0,))
    linear.add_color_stop_rgba(prog - pulse_hwidth, *color + (0,))
    linear.add_color_stop_rgba(prog,                *color + (1,))
    linear.add_color_stop_rgba(prog + pulse_hwidth, *color + (0,))
    linear.add_color_stop_rgba(1.0,                 *color + (0,))
    cairo_context.set_source(linear)
    cairo_context.rectangle(0, 0, width, height)
    cairo_context.fill()

  def draw_icon(self, cairo_context):
    height = self.sourceview.line_height

    if not self.icon:
      if hasattr(self.source, 'favicon_data') and self.source.favicon_data:
        try:
          loader = gtk.gdk.PixbufLoader()
          loader.set_size(16, 16)
          loader.write(self.source.favicon_data)
          loader.close()
          self.icon = loader.get_pixbuf()
        except glib.GError:
          self.source.reject_favicon()

    if not self.icon and self.source.icon:
      try:
        theme = gtk.icon_theme_get_default()
        self.icon = theme.load_icon(self.source.icon, 16, 0)
      except:
        pass

    shift = 0

    if self.source.progress > 0:
      shift = 20 # icon width + 4
      pie_color = self.sourceview.color('pie', selected=self.is_selected)

      cairo_context.set_source_rgb(*pie_color)
      cairo_context.new_sub_path()
      cairo_context.arc(20 + 8, height * 0.5, 8, 0, 2*pi)
      cairo_context.set_line_width(1)
      cairo_context.stroke()

      cairo_context.set_source_rgb(*pie_color)
      cairo_context.move_to(20 + 8, height * 0.5)
      cairo_context.arc(20 + 8, height * 0.5, 8, -pi/2,
          (2 * pi * self.source.progress / 100) - (pi/2))
      cairo_context.line_to(20 + 8, height * 0.5)
      cairo_context.fill()

    elif self.icon:
      icon_alpha = 0.3 if self.source.progress < 0 else 1
      shift = 20 # icon width + 4
      cairo_context.set_source_pixbuf(self.icon, 20, leading(height, 16) / 2)
      cairo_context.paint_with_alpha(icon_alpha)

    return shift

  def leading(self, height):
    return leading(self.height, height)

  def half_leading(self, height):
    return self.leading(height) / 2

  def draw(self, cairo_context):
    def draw_item_text(color_name, dy):
      fd = self.sourceview.font_desc.copy()
      fd.set_weight(weight)

      # we're abusing 'fosused' here...
      self.sourceview.draw_text(fd, cairo_context, self.label,
          color_name, label_width, self.height, dx, dy,
          selected=self.is_selected,
          focused=(unread > 0))

    def draw_pill():
      padding = 5
      lr_margin = 4
      tb_margin = 3
      if self.source.unread < 1: return lr_margin

      layout = cairo_context.create_layout()
      layout.set_wrap(False)
      fd = self.sourceview.font_desc.copy()
      fd.set_weight(700)
      layout.set_font_description(fd)
      layout.set_text(locale.format('%d', self.source.unread, grouping=True))
      text_width, text_height = layout.get_pixel_size()

      if text_width >= self.width - dx: return lr_margin
      pill_height = self.height - 2 * tb_margin
      pill_width = max(text_width + 2 * padding, int(1.5 * pill_height))

      text_offset = (pill_width - text_width) * 0.5

      self.sourceview.set_color(cairo_context, 'pill-bg',
          selected=self.is_selected)
      graphics.rounded_rect(cairo_context, self.width - pill_width - lr_margin, tb_margin,
          pill_width, pill_height, 1000)
      cairo_context.fill()

      self.sourceview.set_color(cairo_context, 'pill-fg',
          selected=self.is_selected)
      cairo_context.move_to(
          self.width - text_width - text_offset - lr_margin - 0.5,
          leading(self.height, text_height) * 0.5)
      cairo_context.show_layout(layout)

      return pill_width + 2 * lr_margin

    if self.is_selected:
      bot_grad_color = self.sourceview.color('item-bg-bottom')
      top_grad_color = mix(0.30, bot_grad_color, (1, 1, 1))
      top_line_color = mix(0.18, bot_grad_color, (1, 1, 1))

      linear = cairo.LinearGradient(0, 0, 0, self.height)
      linear.add_color_stop_rgb(0, *top_grad_color)
      linear.add_color_stop_rgb(1, *bot_grad_color)
      cairo_context.set_source(linear)
      cairo_context.rectangle(0, 0, self.width, self.height)
      cairo_context.fill()

      cairo_context.set_source_rgb(*top_line_color)
      cairo_context.move_to(0 + 0.5, 0 + 0.5)
      cairo_context.line_to(self.width + 0.5, 0 + 0.5)
      cairo_context.set_line_width(1)
      cairo_context.stroke()

    self.draw_flash(cairo_context)
    dx = 20
    dx += self.draw_icon(cairo_context)

    pill_width = draw_pill()

    label_width = self.width - dx - pill_width

    unread = self.source.unread
    weight = (400, 700)[self.is_selected or unread > 0]
    draw_item_text('item-fg-shadow', 1)
    draw_item_text('item-fg', 0)

