import sched
import time
from functools import wraps


def outputs(**outs):
    def dec(cls):
        for name, out in outs.items():
            assert not hasattr(cls, name)
            setattr(cls, name, out)
        return cls
    return dec


class Output:
    def __init__(self):
        self.down = []

    def attach(self, _, down):
        self.down.append(down)
        down.__self__.up[down] = self


class EventOutput(Output):
    _port_type = 'Eo'

    def __call__(self, ev):
        for d in self.down:
            d(ev)


def input_attach(me, up):
    me.__self__.up[me] = up
    up.down.append(me)


def event_input(f):
    f.attach = input_attach
    f._port_type = 'Ei'
    return f


class ValueOutput(Output):
    _port_type = 'Vo'

    def __call__(self, val):
        self.prev_val = self.val
        self.val = val
        for d in self.down:
            d(self.prev_val, self.val)


def value_input(f):
    f.attach = input_attach
    f._port_type = 'Vi'
    return f


class MutexPort:
    _port_type = 'M'

    def __init__(self, f):
        self.f = f

    def attach(self, peer):
        self.peer = peer
        peer.peer = self


# TODO: What type is `timestamp`? Return type of `time.monotonic()`? `datetime`?
class Event:
    def __init__(self, timestamp, data):
        self.timestamp = timestamp
        self.data = data

    def __repr__(self):
        return f"Event({self.timestamp!r}, {self.data!r})"

    def __str__(self):
        return f"{self.data!r} @ {self.timestamp}"


class Actor:
    def __init__(self):
        self.up = {}

    def attach(self, **connections):
        for my_port_name, peer_port in connections.items():
            my_port = getattr(self, my_port_name)
            peer_port_expected_type = {
                'Eo': 'Ei',
                'Ei': 'Eo',
                'Vo': 'Vi',
                'Vi': 'Vo',
                'M': 'M',
            }[my_port._port_type]
            if peer_port_expected_type != peer_port._port_type:
                raise Exception(
                    f"{my_port._port_type} port can't "
                    f"connect to {peer_port._port_type} port"
                )
            my_port.attach(my_port, peer_port)


@outputs(
    expiration=EventOutput(),
)
class Timer(Actor):
    def __init__(self, interval_sec):
        super().__init__()
        self.interval_sec = interval_sec

    def start(self, mgr):
        self.mgr = mgr
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
        self.expiration(Event(time.monotonic(), None))  # TODO: timestamp type


class Action(Actor):
    def __init__(self, f):
        super().__init__()
        self.f = f

    @event_input
    def trigger(self, ev):
        self.f(ev)


@outputs(
    val=ValueOutput(),
)
class Buffer(Actor):
    def __init__(self, initial):
        super().__init__()
        self.val.val = initial

    @event_input
    def event(self, ev):
        self.val(ev.data)


@outputs(
    new=EventOutput(),
)
class Watch(Actor):
    @value_input
    def val(self, _prev_val, val):
        self.new(Event(time.monotonic(), val))


class Manager:
    def __init__(self):
        self.scheduler = sched.scheduler()
        self.t0 = time.monotonic()


t = Timer(1)
a1 = Action(lambda x: print(f"1: {x}"))
a2 = Action(lambda x: print(f"2: {x}"))
b = Buffer(None)
w = Watch()
t.attach(expiration=a1.trigger)
b.attach(event=t.expiration)
w.attach(val=b.val)
a2.attach(trigger=w.new)
mgr = Manager()
t.start(mgr)
mgr.scheduler.run()
