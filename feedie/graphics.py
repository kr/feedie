from math import pi
from collections import namedtuple

def rounded_rect(context, x, y, w, h, r):
  context.save()
  context.translate(x, y)

  # Nine pieces.
  #    xa  xb  w
  #    |   |
  # ---+---+--- ya
  #    |   |
  # ---+---+--- yb
  #    |   |
  #             h

  xm = w / 2
  ym = h / 2
  r = min(xm, ym)

  xa = min(xm, r)
  xb = max(xm, w - r)

  ya = min(ym, r)
  yb = max(ym, h - r)

  context.move_to(0, ya)
  context.arc(xa, ya, r, pi, 3*pi/2)
  context.line_to(xb, 0)
  context.arc(xb, ya, r, 3*pi/2, 0)
  context.line_to(w, ya)
  context.arc(xb, yb, r, 0, pi/2)
  context.line_to(xa, h)
  context.arc(xa, yb, r, pi/2, pi)

  context.restore()
