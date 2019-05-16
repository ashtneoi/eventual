import enum
import sched
import time


sch = sched.scheduler()


class Kind(enum.Enum):
    EVENT = enum.auto()
    VALUE = enum.auto()


class Any:
    pass


class Actor:
    def __init__(self):
        self.downstream = []


class EventActor(Actor):
    def recv_event(self, _ev):
        raise Exception


class ValueActor(Actor):
    def recv_change(self, _old_val, _new_val):
        raise Exception


class Buffer(EventActor):
    out_kind = VALUE

    def __init__(self, initial):
        super().__init__()
        self.out_value = initial

    def recv_event(self, ev):
        self.out_value = ev.value


class Timer(Actor):
    out_kind = VALUE

    def __init__(self, interval):
        super().__init__()
        self.interval = interval
        self.expire = self.mgr.start_time
        self.sched_next()

    def sched_next(self):
        self.expire += self.inverval
        self.sched_event = sch.enterabs(self.expire, 1, self.send_event)

    def send_event(self):
        self.sched_next()
        for d in self.downstream:
            d.recv_event(None)


class Action(EventActor):
    def __init__(self, f):
        super().__init__()
        self.f = f

    def 


class Fork(EventActor):
    pass
