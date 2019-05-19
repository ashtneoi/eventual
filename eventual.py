import sched
import time
import unittest
from functools import update_wrapper


class Creator:
    def __set_name__(self, owner, name):
        self.name = name


class Input:
    def __init__(self, actor, f):
        self.actor = actor
        self.f = f

        self.up = None

    def __call__(self, thing):
        self.f(self.actor, thing)


class EventInputInstance(Input):
    def attach(self, up):
        if not isinstance(up, EventOutputInstance):
            raise Exception(
                f"Can't connect {type(self)} to {type(up)}"
            )
        up.down.append(self)
        self.up = up


class EventInput(Creator):
    def __init__(self, f):
        self.f = f

    def __get__(self, instance, owner):
        # Create instance attribute to override us.
        obj = EventInputInstance(instance, self.f)
        setattr(instance, self.name, obj)
        return obj


class ValueInputInstance(Input):
    def attach(self, up):
        if not isinstance(up, ValueOutputInstance):
            raise Exception(
                f"Can't connect {type(self)} to {type(up)}"
            )
        up.down.append(self)
        self.up = up


class ValueInput(Creator):
    def __init__(self, f):
        self.f = f

    def __get__(self, instance, owner):
        # Create instance attribute to override us.
        obj = ValueInputInstance(instance, self.f)
        setattr(instance, self.name, obj)
        return obj


class EventOutputInstance:
    def __init__(self, actor):
        self.actor = actor

        self.down = []

    def attach(self, down):
        if not isinstance(up, EventInputInstance):
            raise Exception(
                f"Can't connect {type(self)} to {type(up)}"
            )
        down.up = self
        self.down.append(down)

    def __call__(self, ev):
        for d in self.down:
            d(ev)


class EventOutput(Creator):
    def __get__(self, instance, owner):
        # Create instance attribute to override us.
        obj = EventOutputInstance(instance)
        setattr(instance, self.name, obj)
        return obj


class SyncInstance:
    def __init__(self, actor, f):
        self.actor = actor
        self.f = f

        self.peer = None

    def __call__(self, val):
        if self.peer is not None:
            self.peer.f(self.peer.actor, val)

    def attach(self, peer):
        if self.peer is not None:
            raise Exception("Can only attach once")
        if not isinstance(peer, SyncInstance):
            raise Exception(
                f"Can't connect {type(self)} to {type(peer)}"
            )
        peer.peer = self
        self.peer = peer


class Sync(Creator):
    def __init__(self, f):
        self.f = f

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner):
        # Create instance attribute to override us.
        obj = SyncInstance(instance, self.f)
        setattr(instance, self.name, obj)
        return obj


def event_input(f):
    e = EventInput(f)
    update_wrapper(e, f)
    return e


def value_input(f):
    e = ValueInput(f)
    update_wrapper(e, f)
    return e


def sync(f):
    e = Sync(f)
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
    def test_event_input_output(self):
        class Thing(Actor):
            trigger = EventOutput()

            def __init__(self):
                self.a = 0

            @event_input
            def hey(self, ev):
                self.a = ev.data

        x = Thing()
        y = Thing()
        x.attach(hey=y.trigger)

        self.assertEqual(x.a, 0)
        self.assertEqual(y.a, 0)
        x.trigger(Event(100))
        self.assertEqual(x.a, 0)
        self.assertEqual(y.a, 0)
        y.trigger(Event(200))
        self.assertEqual(x.a, 200)
        self.assertEqual(y.a, 0)

    def test_sync(self):
        class Thing(Actor):
            def __init__(self):
                self.a = 0

            @sync
            def hey(self, val):
                self.a = val

        x = Thing()
        y = Thing()
        x.attach(hey=y.hey)

        self.assertEqual(x.a, 0)
        self.assertEqual(y.a, 0)
        x.hey(100)
        self.assertEqual(x.a, 0)
        self.assertEqual(y.a, 100)
        y.hey(200)
        self.assertEqual(x.a, 200)
        self.assertEqual(y.a, 100)
