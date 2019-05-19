import sched
import time
import unittest
from functools import update_wrapper


class Creator:
    def __set_name__(self, owner, name):
        self.name = name


class PortInstance:
    def __repr__(self):
        return f"<{type(self).__name__}: {self.name}>"


class InputInstance(PortInstance):
    def __init__(self, name, actor, f):
        self.name = name
        self.actor = actor
        self.f = f

        self.up = None

    def __call__(self, thing):
        self.f(self.actor, thing)

    def poke(self):
        if self.up is not None:
            self.up.actor.poke()


class EventInputInstance(InputInstance):
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
        obj = EventInputInstance(self.name, instance, self.f)
        setattr(instance, self.name, obj)
        return obj


class ValueInputInstance(InputInstance):
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
        obj = ValueInputInstance(self.name, instance, self.f)
        setattr(instance, self.name, obj)
        return obj


class EventOutputInstance(PortInstance):
    def __init__(self, name, actor):
        self.name = name
        self.actor = actor

        self.down = []

    def attach(self, down):
        if not isinstance(down, EventInputInstance):
            raise Exception(
                f"Can't connect {type(self)} to {type(up)}"
            )
        down.up = self
        self.down.append(down)

    def __call__(self, ev):
        for d in self.down:
            d(ev)

    def poke(self):
        for d in self.down:
            d.actor.poke()


class EventOutput(Creator):
    def __get__(self, instance, owner):
        # Create instance attribute to override us.
        obj = EventOutputInstance(self.name, instance)
        setattr(instance, self.name, obj)
        return obj


class ValueOutputInstance(PortInstance):
    def __init__(self, name, actor, initial):
        self.name = name
        self.actor = actor
        self.initial = initial

        self.down = []

    def attach(self, down):
        if not isinstance(up, ValueInputInstance):
            raise Exception(
                f"Can't connect {type(self)} to {type(up)}"
            )
        down.up = self
        self.down.append(down)

    def __call__(self, val):
        self.val = val
        for d in self.down:
            d.val = val
            d(val)

    def poke(self):
        self(self.initial)
        for d in self.down:
            d.actor.poke()


class ValueOutput(Creator):
    def __init__(self, initial):
        self.initial = initial

    def __get__(self, instance, owner):
        # Create instance attribute to override us.
        obj = ValueOutputInstance(self.name, instance, self.initial)
        setattr(instance, self.name, obj)
        return obj


class SyncInstance(PortInstance):
    def __init__(self, name, actor, f):
        self.name = name
        self.actor = actor
        self.f = f

        self.peer = None
        self.want = False

    def attach(self, peer):
        if self.peer is not None:
            raise Exception("Can only attach once")
        if not isinstance(peer, SyncInstance):
            raise Exception(
                f"Can't connect {type(self)} to {type(peer)}"
            )
        peer.peer = self
        self.peer = peer

    def poke(self):
        if self.peer is not None:
            self.peer.actor.poke()

    def __call__(self, want):
        self.want = want
        if self.peer is None:
            raise Exception("Peer is not set")
        self.peer.f(self.peer.actor, want)

    @property
    def val(self):
        if self.peer is None:
            raise Exception("Peer is not set")
        return self.want and self.peer.want


class Sync(Creator):
    def __init__(self, f):
        self.f = f

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner):
        # Create instance attribute to override us.
        obj = SyncInstance(self.name, instance, self.f)
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


class Event:
    def __init__(self, data, timestamp=None):
        self.data = data
        if timestamp is None:
            self.timestamp = time.monotonic()
        else:
            self.timestamp = timestamp

    def __str__(self):
        return f"{self.data!r} @ {self.timestamp:.2f}"


class Manager:
    def __init__(self):
        self.actors = []

    def add(self, actor):
        self.actors.append(actor)

    def start(self):
        self.scheduler = sched.scheduler()
        self.t0 = time.monotonic()
        for actor in self.actors:
            actor.poke()

    def run(self):
        self.scheduler.run()


class Actor:
    poked = False

    def __init__(self, mgr):
        self.mgr = mgr
        mgr.add(self)

    def attach(self, **connections):
        for key, val in connections.items():
            getattr(self, key).attach(val)

    def poke(self):
        if self.poked:
            return
        self.poked = True
        for attr in tuple(self.__dict__.values()):
            if isinstance(attr, PortInstance):
                attr.poke()


class Timer(Actor):
    trigger = EventOutput()

    def __init__(self, mgr, interval_sec):
        super().__init__(mgr)
        self.interval_sec = interval_sec

    def poke(self):
        super().poke()
        self.next_event_time_sec = self.mgr.t0
        self.on_expire()

    def on_expire(self):
        # TODO: This may not cope well with very long OS/program uptime.
        now = time.monotonic()
        advance_by = (
            ((now - self.next_event_time_sec) // self.interval_sec)
            * self.interval_sec
            + self.interval_sec
        )
        self.next_event_time_sec += advance_by
        self.mgr.scheduler.enterabs(
            self.next_event_time_sec,
            0,
            self.on_expire,
        )
        self.trigger(Event(None))


class LogEvent(Actor):
    event_out = EventOutput()

    @event_input
    def event_in(self, ev):
        print(ev)
        self.event_out(ev)


class Test(unittest.TestCase):
    def test_value_input_output(self):
        class Thing(Actor):
            trigger = ValueOutput('nope')

            def __init__(self, mgr):
                super().__init__(mgr)
                self.a = 0

            @value_input
            def hey(self, val):
                self.a = val

        mgr = Manager()
        x = Thing(mgr)
        y = Thing(mgr)
        x.attach(hey=y.trigger)
        mgr.start()

        self.assertEqual(x.a, 'nope')
        self.assertEqual(x.hey.val, 'nope')
        self.assertEqual(y.a, 0)
        x.trigger(100)
        self.assertEqual(x.a, 'nope')
        self.assertEqual(y.a, 0)
        y.trigger(200)
        self.assertEqual(x.a, 200)
        self.assertEqual(y.a, 0)

    def test_event_input_output(self):
        class Thing(Actor):
            trigger = EventOutput()

            def __init__(self, mgr):
                super().__init__(mgr)
                self.a = 0

            @event_input
            def hey(self, ev):
                self.a = ev.data

        mgr = Manager()
        x = Thing(mgr)
        y = Thing(mgr)
        x.attach(hey=y.trigger)
        mgr.start()

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
            def __init__(self, mgr):
                self.a = 0

            @sync
            def hey(self, val):
                self.a = val

        mgr = Manager()
        x = Thing(mgr)
        y = Thing(mgr)
        x.attach(hey=y.hey)
        mgr.start()

        self.assertEqual(x.hey.want, False)
        self.assertEqual(x.hey.val, False)
        self.assertEqual(x.a, 0)
        self.assertEqual(y.hey.want, False)
        self.assertEqual(y.hey.val, False)
        self.assertEqual(y.a, 0)
        x.hey(False)
        self.assertEqual(x.hey.want, False)
        self.assertEqual(x.hey.val, False)
        self.assertEqual(x.a, 0)
        self.assertEqual(y.hey.want, False)
        self.assertEqual(y.hey.val, False)
        self.assertEqual(y.a, False)
        y.hey(True)
        self.assertEqual(x.hey.want, False)
        self.assertEqual(x.hey.val, False)
        self.assertEqual(x.a, True)
        self.assertEqual(y.hey.want, True)
        self.assertEqual(y.hey.val, False)
        self.assertEqual(y.a, False)
        x.hey(True)
        self.assertEqual(x.hey.want, True)
        self.assertEqual(x.hey.val, True)
        self.assertEqual(x.a, True)
        self.assertEqual(y.hey.want, True)
        self.assertEqual(y.hey.val, True)
        self.assertEqual(y.a, True)


if __name__ == '__main__':
    mgr = Manager()
    t = Timer(mgr, 2)
    l = LogEvent(mgr)
    t.attach(trigger=l.event_in)
    mgr.start()
    mgr.run()
