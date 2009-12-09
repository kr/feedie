import gtk
import glib
import math
import cairo
import pango
import gobject
import time

from feedie.feedieconfig import *
from feedie.util import *
from feedie import graphics

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
    self.rev_lines = {}
    self.selected_id = None
    self.sources = sources
    self.sources.add_listener(self)
    self.items = {}
    self.update(self.sources)

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

  def update(self, item, arg=None):
    self.update_heading_order()
    self.update_heading_items()
    self.set_size_request(-1, self.height_request)
    if self.selected_id not in self.items:
      self.select(None)
    self.invalidate()

  @property
  def height_request(self):
    return self.line_height * len(self.lines)

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
    line = int(event.y / self.line_height)
    item = self.lines.get(line, None)
    if item:
      self.select(item.id)

  def get_y(self, item_id):
    return self.line_height * self.rev_lines[item_id]

  def select(self, item_id):
    if self.selected_id != item_id:
      prev = self.selected_view
      self.selected_id = item_id
      if prev: prev.invalidate()
      if self.selected_view: self.selected_view.invalidate()
      self.emit('selection-changed', self.selected_id)

  def expose(self, widget, event):
    cairo_context = widget.window.cairo_create()

    # set a clip region for the expose event
    cairo_context.rectangle(event.area.x, event.area.y,
                           event.area.width, event.area.height)
    cairo_context.clip()

    self.draw(cairo_context)
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

  @property
  def line_height(self):
    return max(self.approx_text_height + self.approx_text_height / 2 - 1, 10)

  @property
  def width(self):
    rect = self.get_allocation()
    return rect.width

  def draw(self, cairo_context):
    def draw_line(line, f, *args, **kwargs):
      cairo_context.save()
      try:
        cairo_context.translate(0, line * self.line_height)
        return f(*args, **kwargs)
      finally:
        cairo_context.restore()

    rect = self.get_allocation()
    x = rect.x + rect.width / 2
    y = rect.y + rect.height / 2

    radius = min(rect.width / 2, rect.height / 2) - 5

    # background
    #cairo_context.set_source_rgb(0.82, 0.85, 0.90)
    cairo_context.set_source_rgb(0xd7/255.0, 0xdd/255.0, 0xe6/255.0) # copy
    cairo_context.rectangle(0, 0, rect.width, rect.height)
    cairo_context.fill()

    line = 0
    self.lines = {}
    self.rev_lines = {}
    for heading_name in self.heading_order:
      items = self.heading_items[heading_name]
      draw_line(line, draw_heading, self, cairo_context, heading_name)
      line += 1
      for item in items:
        if item.is_selectable():
          self.lines[line] = item
          self.rev_lines[item.id] = line
        draw_line(line, item.draw, cairo_context)
        line += 1
      line += 1 # margin

  def flash(self, item_id):
    if item_id not in self.items: return
    self.items[item_id].flash()
    glib.idle_add(self.update_flash_anim)

  def update_flash_anim(self):
    ret = False
    # TODO functionalize
    for item in self.items.values():
      if item.is_flashing():
        item.invalidate()
        ret = True
    return ret

  def invalidate_rect(self, x, y, width, height):
    rect = gtk.gdk.Rectangle(x, y, width, height)
    if self.window:
      # TODO investigate queue_draw_area
      self.window.invalidate_rect(rect, True)

  def invalidate(self):
    alloc = self.get_allocation()
    self.invalidate_rect(0, 0, alloc.width, alloc.height)

def draw_text(font_desc, cairo_context, text, rgba, width, height, dx, dy):
  if width < 1: return
  cairo_context.set_source_rgba(*rgba)
  layout = cairo_context.create_layout()
  layout.set_width(width * pango.SCALE)
  layout.set_wrap(False)
  layout.set_ellipsize(pango.ELLIPSIZE_END)
  layout.set_font_description(font_desc)
  layout.set_text(text)
  text_width, text_height = layout.get_pixel_size()
  cairo_context.move_to(dx, leading(height, text_height) / 2 + dy)
  cairo_context.show_layout(layout)

def draw_heading(sourceview, cairo_context, text):
  baseline = 5
  text = text.upper()

  label_width = sourceview.width - 10

  fd = sourceview.font_desc.copy()
  fd.set_weight(700)
  draw_text(fd, cairo_context, text, (1, 1, 1, 0.5),
      label_width, sourceview.line_height, 10, 1)

  draw_text(fd, cairo_context, text, (0.447, 0.498, 0.584, 1),
      label_width, sourceview.line_height, 10, 0)

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
    source.add_listener(self)

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

  def update(self, item, arg=None):
    self.invalidate()

  def invalidate_rect(self, x, y, width, height):
    self.sourceview.invalidate_rect(self.x + x, self.y + y, width, height)

  def invalidate(self):
    self.invalidate_rect(0, 0, self.width, self.height)

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
    #icon = cairo.ImageSurface.create_from_png(self.source.icon_path)
    theme = gtk.icon_theme_get_default()
    try:
      icon = theme.load_icon(self.source.icon, 16, 0)
    except:
      icon = None

    shift = 0
    if icon:
      cairo_context.set_source_pixbuf(icon, 20, leading(height, 16) / 2)
      cairo_context.paint()
      shift = 20 # icon width + 4
    return shift

  def leading(self, height):
    return leading(self.height, height)

  def half_leading(self, height):
    return self.leading(height) / 2

  def draw(self, cairo_context):
    def draw_my_text(weight, rgba, dy):
      fd = self.sourceview.font_desc.copy()
      fd.set_weight(weight)
      draw_text(fd, cairo_context, self.label,
          rgba, label_width, self.height, dx, dy)

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
      layout.set_text(str(self.source.unread))
      text_width, text_height = layout.get_pixel_size()

      if text_width >= self.width - dx: return lr_margin
      pill_width = text_width + 2 * padding

      if self.is_selected:
        cairo_context.set_source_rgb(1, 1, 1)
      else:
        #cairo_context.set_source_rgb(0.15, 0.23, 0.99)
        #cairo_context.set_source_rgb(0x8f/255.0, 0xac/255.0, 0xe0/255.0)
        cairo_context.set_source_rgb(0x76/255.0, 0x96/255.0, 0xd0/255.0)
      graphics.rounded_rect(cairo_context, self.width - pill_width - lr_margin, tb_margin,
          pill_width, self.height - 2 * tb_margin, 1000)
      cairo_context.fill()

      if self.is_selected:
        cairo_context.set_source_rgb(0.35, 0.35, 0.35)
      else:
        cairo_context.set_source_rgb(1, 1, 1)
      cairo_context.move_to(self.width - text_width - padding - lr_margin,
          leading(self.height, text_height) / 2)
      cairo_context.show_layout(layout)



      return pill_width + 2 * lr_margin

    if self.is_selected:
      bot_grad_color = (0.129, 0.361, 0.729)
      top_grad_color = mix(0.30, bot_grad_color, (1, 1, 1))
      #top_grad_color = (0.153, 0.420, 0.851)
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

    if self.is_selected:
      draw_my_text(700, (0, 0, 0, 0.5), 1)
      draw_my_text(700, (1, 1, 1, 1.0), 0)
    else:
      weight, color = (
          (400, (0.10, 0.10, 0.10, 1.0)),
          (700, (0.20, 0.20, 0.20, 1.0)),
        )[self.source.unread > 0]
      draw_my_text(weight, color, 0)

