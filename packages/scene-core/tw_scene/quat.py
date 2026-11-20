from __future__ import annotations

import math

Vec = list  # [x, y, z]
Quat = list  # [w, x, y, z]


def qnorm(q):
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return [c / n for c in q]


def qmul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return [aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw]


def qconj(q):
    return [q[0], -q[1], -q[2], -q[3]]


def qrot(q, v):
    p = qmul(qmul(q, [0.0, *v]), qconj(q))
    return p[1:]


def qaxis(axis, angle):
    n = math.sqrt(sum(c * c for c in axis)) or 1.0
    s = math.sin(angle / 2.0)
    return [math.cos(angle / 2.0), axis[0] / n * s, axis[1] / n * s, axis[2] / n * s]


def qangle_about(q, axis):
    """Signed rotation angle of q about a unit axis (twist decomposition), in radians, in (-pi, pi]."""
    n = math.sqrt(sum(c * c for c in axis)) or 1.0
    ax = [c / n for c in axis]
    proj = q[1] * ax[0] + q[2] * ax[1] + q[3] * ax[2]
    ang = 2.0 * math.atan2(proj, q[0])
    if ang > math.pi:
        ang -= 2 * math.pi
    if ang <= -math.pi:
        ang += 2 * math.pi
    return ang


def add(a, b):
    return [a[i] + b[i] for i in range(3)]


def sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def scale(a, s):
    return [c * s for c in a]


def dot(a, b):
    return sum(a[i] * b[i] for i in range(3))
