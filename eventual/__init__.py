import sched
import time
import unittest
from functools import update_wrapper


class PortNotConnected(Exception):
    pass


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


class EventInputInstance(InputInstance):
    def attach(self, up):
        up.attach(self)

    def detach(self):
        self.up.down.remove(self)
        self.up.actor.after_detach(self.up)
        self.up = None
        self.actor.after_detach(self)


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
        up.attach(self)

    def detach(self):
        self.up.down.remove(self)
        self.up.actor.after_detach(self.up)
        self.up = None
        self.actor.after_detach(self)

    @property
    def val(self):
        if self.up is None:
            raise PortNotConnected
        return self.up.val


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

    def detach(self):
        for down in self.down:
            down.up = None
            down.actor.after_detach(down)
        self.down = []
        self.actor.after_detach(self)

    def __call__(self, ev):
        for d in self.down:
            d(ev)


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
        self.val = initial

        self.down = []

    def attach(self, down):
        if not isinstance(down, ValueInputInstance):
            raise Exception(
                f"Can't connect {type(self)} to {type(up)}"
            )
        down.up = self
        self.down.append(down)
        down(self.val)

    def detach(self):
        for down in self.down:
            down.up = None
            down.actor.after_detach(down)
        self.down = []
        self.actor.after_detach(self)

    def __call__(self, val):
        self.val = val
        for d in self.down:
            d(val)


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
            raise Exception("Port is already connected")
        if not isinstance(peer, SyncInstance):
            raise Exception(
                f"Can't connect {type(self)} to {type(peer)}"
            )
        peer.peer = self
        self.peer = peer
        peer(self.want)
        self(peer.want)

    def detach(self):
        self.peer.peer = None
        self.peer.actor.after_detach(self.peer)
        self.peer = None
        self.actor.after_detach(self)

    def __call__(self, want):
        self.want = want
        if self.peer is not None:
            self.peer.f(self.peer.actor, want)

    @property
    def val(self):
        if self.peer is None:
            raise PortNotConnected
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
        self.scheduler = sched.scheduler()

    def add(self, actor):
        self.actors.append(actor)

    def run(self):
        self.scheduler.run()


class Actor:
    def __init__(self, mgr):
        self.mgr = mgr
        mgr.add(self)

    def attach(self, **connections):
        for key, val in connections.items():
            getattr(self, key).attach(val)

    def after_detach(self, _port):
        pass


class IntervalTimer(Actor):
    trigger = EventOutput()
    late = EventOutput()

    def __init__(self, mgr, interval_sec):
        super().__init__(mgr)
        self.interval_sec = interval_sec
        self.next_event = None

    @value_input
    def active(self, val):
        if val:
            if self.next_event is None:
                self.next_event_time_sec = time.monotonic()
                self._on_expire()
        else:
            if self.next_event is not None:
                self.mgr.scheduler.cancel(self.next_event)
                self.next_event = None

    def _on_expire(self):
        now = time.monotonic()
        self.next_event_time_sec += self.interval_sec
        if self.next_event_time_sec < now:
            self.next_event_time_sec = now + self.interval_sec
            self.late(Event(None, now))
        self.next_event = self.mgr.scheduler.enterabs(
            self.next_event_time_sec,
            0,
            self._on_expire,
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

        self.assertEqual(x.a, 'nope')
        self.assertEqual(x.hey.val, 'nope')
        self.assertEqual(y.a, 0)
        x.trigger(100)
        self.assertEqual(x.a, 'nope')
        self.assertEqual(x.hey.val, 'nope')
        self.assertEqual(y.a, 0)
        y.trigger(200)
        self.assertEqual(x.a, 200)
        self.assertEqual(x.hey.val, 200)
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

    def test_detach(self):
        class Thing(Actor):
            s = 0
            h = 0
            g = 0

            my_status = ValueOutput(None)
            hello = EventOutput()

            @value_input
            def status(self, _val):
                self.s += 1

            @event_input
            def hey(self, _ev):
                self.h += 1

            @sync
            def go(self, _val):
                self.g += 1

        mgr = Manager()
        x = Thing(mgr)
        y = Thing(mgr)

        with self.assertRaises(PortNotConnected):
            x.go.val
        with self.assertRaises(PortNotConnected):
            y.status.val
        with self.assertRaises(PortNotConnected):
            y.go.val

        x.attach(my_status=y.status)
        x.attach(hello=y.hey)
        x.attach(go=y.go)

        self.assertEqual(y.s, 1)
        self.assertEqual(y.h, 0)
        self.assertEqual(y.g, 1)

        x.my_status(10)
        x.hello(Event("h"))
        x.go(True)

        self.assertEqual(y.status.val, 10)

        self.assertEqual(y.s, 2)
        self.assertEqual(y.h, 1)
        self.assertEqual(y.g, 2)

        x.my_status.detach()
        x.hello.detach()
        x.go.detach()

        with self.assertRaises(PortNotConnected):
            x.go.val
        with self.assertRaises(PortNotConnected):
            y.status.val
        with self.assertRaises(PortNotConnected):
            y.go.val

        x.attach(my_status=y.status)
        x.attach(hello=y.hey)
        x.attach(go=y.go)

        self.assertEqual(y.s, 3)
        self.assertEqual(y.h, 1)
        self.assertEqual(y.g, 3)

        x.my_status(20)
        x.hello(Event("h"))
        x.go(False)

        self.assertEqual(y.s, 4)
        self.assertEqual(y.h, 2)
        self.assertEqual(y.g, 4)


if __name__ == '__main__':
    mgr = Manager()
    t = IntervalTimer(mgr, 2)
    l = LogEvent(mgr)
    t.attach(trigger=l.event_in)
    t.active(True)
    mgr.run()
