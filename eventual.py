import sched
import time
from functools import wraps


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
        prev_val = self.val
        self.val = val
        if prev_val != self.val:
            for d in self.down:
                d(prev_val, self.val)


def value_input(f):
    f.attach = input_attach
    f._port_type = 'Vi'
    return f


def sync_port_attach(me, peer):
    me.__self__.peer[me] = peer
    peer.peer = me


def sync_port(f):
    def sync_port_set(self, want):
        prev_want = self.want[f]
        self.want[f] = want
        if prev_want != self.want:
            self.want[f].peer.f(self.want[f].peer)

    def sync_port_want(self):
        return self.want[f]

    def sync_port_peer_want(self):
        return self.peer[f].__self__.want[self.peer[f]]

    def sync_port_val(self):
        return sync_port_want(self) and sync_port_peer_want(self)

    sync_port_set.f = f
    sync_port_set.attach = sync_port_attach
    sync_port_set.want = sync_port_want
    sync_port_set.peer_want = sync_port_peer_want
    sync_port_set.val = sync_port_val
    sync_port_set._port_type = 'S'

    return sync_port_set


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
    started = False
    out = {}

    def __init__(self):
        self.up = {}
        self.peer = {}
        self.want = {}
        for name, out in self.out.items():
            assert not hasattr(self, name)
            setattr(self, name, out())
        # for name in type(self).__dict__:
            # if not name.startswith('_'):
                # attr = getattr(self, name)
                # if getattr(attr, '_port_type', None) == 'S':
                    # self.sync_want[attr] = False

    def attach(self, **connections):
        for my_port_name, peer_port in connections.items():
            my_port = getattr(self, my_port_name)
            peer_port_expected_type = {
                'Eo': 'Ei',
                'Ei': 'Eo',
                'Vo': 'Vi',
                'Vi': 'Vo',
                'S': 'S',
            }[my_port._port_type]
            if peer_port_expected_type != peer_port._port_type:
                raise Exception(
                    f"{my_port._port_type} port can't "
                    f"connect to {peer_port._port_type} port"
                )
            my_port.attach(my_port, peer_port)

    def start(self, mgr):
        if self.started:
            return
        self.started = True
        for name in self.out:
            for d in getattr(self, name).down:
                d.__self__.start(mgr)


class Timer(Actor):
    out = {
        'expiration': EventOutput,
    }

    def __init__(self, interval_sec):
        super().__init__()
        self.interval_sec = interval_sec

    def start(self, mgr):
        if self.started:
            return
        self.mgr = mgr
        self.next_event_time_sec = self.mgr.t0
        self.on_expire()
        super().start(mgr)

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


class LogEvent(Actor):
    out = {
        'event_out': EventOutput,
    }

    @event_input
    def event_in(self, ev):
        print(ev)
        self.event_out(ev)


class Action(Actor):
    def __init__(self, f):
        super().__init__()
        self.f = f

    @event_input
    def trigger(self, ev):
        self.f(ev)


class Buffer(Actor):
    out = {
        'val': ValueOutput,
    }

    def __init__(self, initial):
        super().__init__()
        self.val.val = initial

    @event_input
    def event(self, ev):
        self.val(ev.data)


class Watch(Actor):
    out = {
        'new': EventOutput,
    }

    @value_input
    def val(self, _prev_val, val):
        self.new(Event(time.monotonic(), val))


class RoundRobinMutexInner(Actor):
    def __init__(self, idx, parent):
        self.idx = idx
        self.parent = parent

    @property
    def is_request(self):
        return not self.sync.want(self) and self.sync.peer_want(self)

    @property
    def is_release(self):
        return self.sync.want(self) and not self.sync.peer_want(self)

    @sync_port
    def sync(self):
        self.parent.handle_change(self.idx)


class RoundRobinMutex(Actor):
    pos = 0
    locked = False

    def __init__(self):
        super().__init__()
        self.inners = []

    def add_port(self):
        inner = RoundRobinMutexInner(len(self.inners), self)
        self.inners.append(inner)

    def next_pos(self, pos):
        return (pos + 1) % len(self.inners)

    def start(self, mgr):
        if self.started:
            return
        self.mgr = mgr
        for idx, inner in enumerate(self.inners):
            if inner.is_request():
                self.locked = True
                self.pos = self.next_pos(idx)
                inner.sync(True)
        super().start(mgr)

    def handle_change(self, idx):
        inner = self.inners[idx]
        if inner.is_release():
            self.locked = False
            inner.sync(False)
            for idx, inner in chain(
                enumerate(self.inners[self.pos:]),
                enumerate(self.inners[:self.pos]),
            ):
                if inner.is_request():
                    self.locked = True
                    self.pos = self.next_pos(idx)
                    inner.sync(True)
        elif inner.is_request():
            if not self.locked:
                self.locked = True
                self.pos = self.next_pos(idx)
                inner.sync(True)


class Manager:
    def __init__(self):
        self.scheduler = sched.scheduler()
        self.t0 = time.monotonic()


t = Timer(1)

log = LogEvent()
log.attach(event_in=t.expiration)

a = Action(lambda ev: print('hi!'))
a.attach(trigger=log.event_out)

mgr = Manager()
t.start(mgr)
mgr.scheduler.run()
