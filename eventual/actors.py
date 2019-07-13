import time
import unittest

from eventual import (
    Actor,
    event_input,
    Event,
    EventOutput,
    Manager,
    sync,
    value_input,
    ValueOutput,
)


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


class _RoundRobinMutexChild(Actor):
    def __init__(self, mgr, parent):
        super().__init__(mgr)
        self.parent = parent

    def after_detach(self, port):
        assert port is self.mutex
        self.parent.after_detach_child(self)

    @sync
    def mutex(self, want):
        self.parent.mutex(self, want)


class RoundRobinMutex(Actor):
    locked = ValueOutput(False)
    pos = 0  # When locked: current holder.

    def __init__(self, mgr):
        super().__init__(mgr)
        self.children = []

    def attach_child(self, **connections):
        child = _RoundRobinMutexChild(self.mgr, self)
        self.children.append(child)
        return child.attach(**connections)

    def after_detach_child(self, child):
        i = self.children.index(child)

        if self.locked.val and child.mutex.want:
            # Child held lock at detach time.
            assert self.pos == i
            self.mutex(child, False)

        self.children.pop(i)
        if self.pos > i:
            self.pos -= 1
        assert self.pos <= len(self.children)
        if self.pos == len(self.children):
            self.pos = 0

    def mutex(self, child, want):
        i = self.children.index(child)
        if want and not self.locked.val:
            # Grant lock.
            assert not child.mutex.want
            self.pos = i
            self.locked(True)
            child.mutex(True)
        elif not want and child.mutex.want:
            # Grant lock to next requester, if any.
            child.mutex(False)
            while True:
                self.pos += 1
                if self.pos == len(self.children):
                    self.pos = 0
                if self.pos == i:
                    self.locked(False)
                    break

                if self.children[self.pos].mutex.peer.want:
                    self.children[self.pos].mutex(True)
                    break


class Test(unittest.TestCase):
    def test_mutex(self):
        class MutexTester(Actor):
            @sync
            def lock(self, want):
                pass

        mgr = Manager()
        t0 = MutexTester(mgr)
        t1 = MutexTester(mgr)
        t2 = MutexTester(mgr)
        m = RoundRobinMutex(mgr)
        m.attach_child(mutex=t0.lock)
        m.attach_child(mutex=t1.lock)

        def check(t0_locked, t1_locked, t2_locked, m_locked):
            if t0_locked is not None:
                self.assertIs(t0.lock.val, t0_locked)
            if t1_locked is not None:
                self.assertIs(t1.lock.val, t1_locked)
            if t2_locked is not None:
                self.assertIs(t2.lock.val, t2_locked)
            self.assertIs(m.locked.val, m_locked)

        check(False, False, None, False)
        t0.lock(True)
        check(True, False, None, True)
        t0.lock(False)
        check(False, False, None, False)

        t0.lock(True)
        check(True, False, None, True)
        t1.lock(True)
        check(True, False, None, True)
        t0.lock(False)
        check(False, True, None, True)
        t0.lock(True)
        check(False, True, None, True)

        m.attach_child(mutex=t2.lock)
        check(False, True, False, True)
        t2.lock(True)
        check(False, True, False, True)
        t1.lock(False)
        check(False, False, True, True)
        t2.lock(False)
        check(True, False, False, True)

        t2.lock(True)
        check(True, False, False, True)
        t0.lock.detach()
        check(None, False, True, True)
        t2.lock.detach()
        check(None, False, None, False)
        t1.lock.detach()
        check(None, None, None, False)
