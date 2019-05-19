import sched
import time
import unittest
from functools import update_wrapper


class EventInputCreator:
    def __init__(self, f):
        self.f = f


class ValueInputCreator:
    def __init__(self, f):
        self.f = f


class Sync:
    def __init__(self, actor, f):
        self.actor = actor
        self.f = f

        self.peer = None

    def __call__(self, ev):
        if self.peer is not None:
            self.peer.f(self.peer.actor, ev)

    def attach(self, peer):
        if self.peer is not None:
            raise Exception("Can only attach once")
        peer.peer = self
        self.peer = peer


class SyncCreator:
    def __init__(self, f):
        self.f = f

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner):
        # Create instance attribute to override us.
        obj = Sync(instance, self.f)
        setattr(instance, self.name, obj)
        return obj


def event_input(f):
    e = EventInputCreator(f)
    update_wrapper(e, f)
    return e


def value_input(f):
    e = ValueInputCreator(f)
    update_wrapper(e, f)
    return e


def sync(f):
    e = SyncCreator(f)
    update_wrapper(e, f)
    return e


class Actor:
    def attach(self, **connections):
        for key, val in connections.items():
            getattr(self, key).attach(val)


class Event:
    def __init__(self, data, timestamp=None):
        self.data = data
        if timestamp is None:
            self.timestamp = time.monotonic()
        else:
            self.timestamp = timestamp


class Test(unittest.TestCase):
    def test(self):
        class Thing(Actor):
            def __init__(self):
                self.a = 0

            @sync
            def hey(self, ev):
                self.a = ev.data

        x = Thing()
        y = Thing()
        x.attach(hey=y.hey)

        self.assertEqual(x.a, 0)
        self.assertEqual(y.a, 0)
        x.hey(Event(100))
        self.assertEqual(x.a, 0)
        self.assertEqual(y.a, 100)
        y.hey(Event(200))
        self.assertEqual(x.a, 200)
        self.assertEqual(y.a, 100)
