import gobject
import gtk
import pango

class Item(object):
  width = 0
  height = 0

  def render(self, ctx, area, flags):
    pass

class ItemShim(Item):
  def __init__(self, width=0, height=0):
    self.width = width
    self.height = height

  def render(self, ctx, area, flags):
    ctx.rectangle(*area)
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()

class ItemIcon(Item):
  @property
  def width(self):
    icon = self.cellr._props['icon']
    if icon: return 16
    return 0

  @property
  def height(self):
    icon = self.cellr._props['icon']
    if icon: return 16
    return 0

  def render(self, ctx, area, flags):
    icon = self.cellr._props['icon']
    if not icon: return

    # Offset to center the icon
    dx = abs(area.width - icon.get_width()) / 2
    dy = abs(area.height - icon.get_height()) / 2

    ctx.set_source_pixbuf(icon, area.x + dx, area.y + dy)
    ctx.paint()

def draw_text(ctx, fd, area, text, dx, dy):
  ctx.set_source_rgb(0, 0, 0)
  layout = ctx.create_layout()
  layout.set_width(area.width * pango.SCALE)
  layout.set_wrap(False)
  layout.set_ellipsize(pango.ELLIPSIZE_END)
  layout.set_font_description(fd)
  layout.set_text(text)
  text_width, text_height = layout.get_pixel_size()
  if text_width > area.width: return

  cy = (area.height - text_height) / 2

  ctx.move_to(area.x + dx, area.y + cy + dy)
  ctx.show_layout(layout)

class ItemText(Item):
  width = 0

  @property
  def height(self):
    fd = self.cellr.widget.get_style().font_desc
    p_ctx = self.cellr.widget.get_pango_context()
    metrics = p_ctx.get_metrics(fd, None)
    approx = (metrics.get_ascent() + metrics.get_descent()) / pango.SCALE
    return max(approx + approx / 2 - 1, 10)

    return 22 # TODO measure text and add leading

  def render(self, ctx, area, flags):
    ctx.rectangle(*area)
    ctx.set_source_rgb(1, 0, 1)
    ctx.fill()

    text = self.cellr._props['text']
    fd = self.cellr.widget.get_style().font_desc
    draw_text(ctx, fd, area, text, 0, 0)



class ItemPill(Item):
  @property
  def width(self):
    unread = self.cellr._props['unread']
    if unread: return 20
    return 0

  @property
  def height(self):
    return 0

  def render(self, ctx, area, flags):
    ctx.rectangle(*area)
    ctx.set_source_rgb(1, 1, 0)
    ctx.fill()

class ItemProg(Item):
  @property
  def width(self):
    return 16

  @property
  def height(self):
    return 0

  def render(self, ctx, area, flags):
    ctx.rectangle(*area)
    ctx.set_source_rgb(0.5, 0.5, 0)
    ctx.fill()

class ItemSpin(Item):
  @property
  def width(self):
    return 16

  @property
  def height(self):
    return 0

  def render(self, ctx, area, flags):
    ctx.rectangle(*area)
    ctx.set_source_rgb(0, 0.5, 0.5)
    ctx.fill()

class CellRendererItems(gtk.GenericCellRenderer):
  __gproperties__ = {
    'text': (str, 'Text', 'Text', '(unknown)', gobject.PARAM_WRITABLE),
    'unread': (int, 'Unread', 'Unread Count', 0, 1000000, 0,
        gobject.PARAM_WRITABLE),
    'progress': (int, 'Progress', 'Progress', 0, 100, 0,
        gobject.PARAM_WRITABLE),
    'spin-start': (float, 'Spin Start', 'Spin Start', 0, 10000000000, 0,
        gobject.PARAM_WRITABLE),
    'spin-update': (int, 'Spin Update', 'Spin Update', 0, 1000000000, 0,
        gobject.PARAM_WRITABLE),
    'icon': (gtk.gdk.Pixbuf, 'Icon', 'Icon', gobject.PARAM_WRITABLE),
    'is_heading': (bool, 'Is Heading', 'Is Heading', False,
        gobject.PARAM_WRITABLE),
  }

  _padding_left = 10
  _padding_between = 2

  _start_items = (
    ItemShim(width=8),
    ItemIcon(),
  )

  _flex_item = ItemText()

  _end_items = (
    ItemPill(),
    ItemProg(),
    ItemSpin(),
  )

  def __init__(self):
    gtk.GenericCellRenderer.__init__(self)
    self._props = {}
    for r in self._items:
      r.cellr = self

  @property
  def _items(self):
    return self._start_items + (self._flex_item,) + self._end_items

  def on_get_size(self, widget, cell_area):
    self.widget = widget
    width = sum(x.width for x in self._items)
    height = max(x.height for x in self._items)
    del self.widget
    return (0, 0, width, height)

  def on_render(self, window, widget, bg_area, cell_area, expose_area, flags):
    try:
      self.widget = widget
      ctx = window.cairo_create()

      # Render background
      if flags & gtk.CELL_RENDERER_SELECTED:
        if widget.props.has_focus:
          ctx.rectangle(*bg_area)
          ctx.set_source_rgb(1, 0, 0)
          ctx.fill()
        else:
          ctx.rectangle(*bg_area)
          ctx.set_source_rgb(0, 1, 0)
          ctx.fill()

      ctx.rectangle(*expose_area)
      ctx.clip()

      area = gtk.gdk.Rectangle(*cell_area)
      for item in self._start_items:
        w = item.width
        if w:
          item_area = gtk.gdk.Rectangle(area.x, area.y, w, area.height)
          item.render(ctx, item_area, flags)

          w += self._padding_between
          area.x += w
          area.width -= w
          if not area.width: return

      for item in self._end_items:
        w = item.width
        if w and w < area.width and area.width > 50:
          item_area = gtk.gdk.Rectangle(area.x + area.width - w, area.y,
              w, area.height)
          item.render(ctx, item_area, flags)

          w += self._padding_between
          area.width -= w
          if not area.width: return

      item = self._flex_item
      if item:
        item.render(ctx, area, flags)
        if not area.width: return

    finally:
      del self.widget

  def on_activate(self, event, widget, path, bg_area, cell_area, flags):
    pass

  def on_start_editing(self, event, widget, path, bg_area, cell_area, flags):
    pass


  def do_set_property(self, k, v):
    self._props[k.name] = v

